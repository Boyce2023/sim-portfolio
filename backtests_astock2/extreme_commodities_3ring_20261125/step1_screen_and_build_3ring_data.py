#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RD028 Step 1:
1. Scan 65+ domestic & global commodity futures up to 2026-11-24/25 for extreme percentiles
   (High: 10Y>=85% or 5Y>=85%; Low: 10Y<=10% or 5Y<=5%) using strictly causal rolling windows.
2. Build verified 3-ring A-share (+ US peer reference) stock baskets for 29 extreme commodities,
   checking every ticker against local a_daily.parquet and A-share code-name registry.
3. Cache clean OHLC, adj_open/adj_close, one-word limit-up (yizi) flags, futures, HOG_SPOT, BDI,
   CSI 300 (sh000300), and S&P 500 (ES_F / ^GSPC).
Strictly NO yfinance imports (D12).
"""
import concurrent.futures
import json
import sys
from pathlib import Path
import akshare as ak
import numpy as np
import pandas as pd

assert "yfinance" not in sys.modules, "D12 violation"

SCRIPT_DIR = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtests_astock2/extreme_commodities_3ring_20261125")
OUT_DIR = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/output/extreme_commodities_3ring_backtest_20261125")
CACHE_DIR = OUT_DIR / "data_cache"
SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

A_DAILY_PATH = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet")
US_DAILY_PATH = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_price_db/all_daily.parquet")
GLOBAL_COMM_DIR = Path("/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_price_db/commodities")
PANEL_V2_PATH = Path("/Users/huaichuaibeimeng/claude-projects/output/csrc_policy_100factors_20261114/policy_polymarket_v1/daily_market_panel_v2_20261124.parquet")

START_DT = pd.Timestamp("2015-01-01")
END_DT = pd.Timestamp("2026-11-24")

CN_FUTURES_UNIVERSE = {
    "RU0": ("天然橡胶", "能化软商品"), "NR0": ("20号胶", "能化软商品"), "BR0": ("丁二烯橡胶", "能化软商品"),
    "MA0": ("甲醇", "煤化工"), "BU0": ("沥青", "能源炼化"), "FU0": ("燃料油", "能源炼化"),
    "LU0": ("低硫燃料油", "能源炼化"), "SC0": ("上海原油", "能源炼化"), "PG0": ("液化石油气", "能源炼化"),
    "CU0": ("沪铜", "有色金属"), "AL0": ("沪铝", "有色金属"), "ZN0": ("沪锌", "有色金属"),
    "PB0": ("沪铅", "有色金属"), "NI0": ("沪镍", "有色金属"), "SN0": ("沪锡", "有色金属"),
    "AO0": ("氧化铝", "有色金属"), "AU0": ("沪金", "贵金属"), "AG0": ("沪银", "贵金属"),
    "EC0": ("欧线集运", "航运指数"),
    "FG0": ("玻璃", "建材黑链"), "SA0": ("纯碱", "建材化工"), "RB0": ("螺纹钢", "黑色金属"),
    "HC0": ("热卷", "黑色金属"), "I0": ("铁矿石", "黑色金属"), "JM0": ("焦煤", "黑色金属"),
    "J0": ("焦炭", "黑色金属"), "SF0": ("硅铁", "铁合金"), "SM0": ("锰硅", "铁合金"),
    "SS0": ("不锈钢", "黑色金属"),
    "PS0": ("多晶硅", "新能源硅链"), "SI0": ("工业硅", "新能源硅链"), "LC0": ("碳酸锂", "新能源锂链"),
    "V0": ("PVC", "氯碱化工"), "SH0": ("烧碱", "氯碱化工"), "TA0": ("PTA", "聚酯化工"),
    "PX0": ("对二甲苯", "聚酯化工"), "PF0": ("短纤", "聚酯化工"), "EG0": ("乙二醇", "聚酯化工"),
    "EB0": ("苯乙烯", "石化化工"), "L0": ("塑料", "聚烯烃"), "PP0": ("聚丙烯", "聚烯烃"),
    "UR0": ("尿素", "农化化肥"),
    "LH0": ("生猪", "农牧生鲜"), "JD0": ("鸡蛋", "农牧生鲜"), "C0": ("国内玉米", "农产品"),
    "CS0": ("玉米淀粉", "农产品"), "M0": ("豆粕", "农产品"), "Y0": ("豆油", "农产品"),
    "P0": ("棕榈油", "农产品"), "A0": ("豆一", "农产品"), "OI0": ("菜油", "农产品"),
    "RM0": ("菜粕", "农产品"), "SR0": ("白糖", "软商品"), "CF0": ("棉花", "软商品"),
    "SP0": ("纸浆", "林浆纸"), "AP0": ("苹果", "生鲜果品"), "CJ0": ("红枣", "生鲜果品"),
    "PK0": ("花生", "农产品"),
}

GLOBAL_FUTURES_UNIVERSE = {
    "GC_F": ("COMEX黄金", "贵金属"), "SI_F": ("COMEX白银", "贵金属"),
    "PL_F": ("NYMEX铂金", "贵金属"), "PA_F": ("NYMEX钯金", "贵金属"),
    "HG_F": ("COMEX铜", "有色金属"), "ALI_F": ("COMEX铝", "有色金属"),
    "CL_F": ("WTI原油", "能源"), "BZ_F": ("布伦特原油", "能源"),
    "NG_F": ("美国天然气", "能源"), "RB_F": ("RBOB汽油", "能源"), "HO_F": ("取暖油", "能源"),
    "LE_F": ("美活牛", "畜牧"), "GF_F": ("美育肥牛", "畜牧"), "HE_F": ("美瘦猪", "畜牧"),
    "ZC_F": ("CBOT玉米", "农产品"), "ZW_F": ("CBOT小麦", "农产品"),
    "ZS_F": ("CBOT大豆", "农产品"), "ZM_F": ("CBOT豆粕", "农产品"), "ZL_F": ("CBOT豆油", "农产品"),
    "SB_F": ("ICE原糖", "软商品"), "CT_F": ("ICE棉花", "软商品"),
    "KC_F": ("ICE咖啡", "软商品"), "CC_F": ("ICE可可", "软商品"), "OJ_F": ("ICE橙汁", "软商品"),
}

# 29 Extreme Commodities -> 3-Ring Verified Stock Baskets (NO ST/delisted)
THREE_RING_MAP = {
    "RU0": {
        "name": "天然橡胶", "group": "HIGH", "driver": "RU0", "alt_driver": "NR0",
        "ring1_logic": "上游天然橡胶种植加工与橡胶助剂核心龙头",
        "ring2_logic": "下游轮胎制造业（天胶占BOM成本约30%至40%，高胶价承压，跌价释放毛利）",
        "ring3_logic": "边缘橡胶制品、输送带与炭黑题材扩散股",
        "ring1": ["601118.SH", "600500.SH", "603650.SH", "300121.SZ"],
        "ring2": ["601058.SH", "601966.SH", "002984.SZ", "000589.SZ", "601500.SH"],
        "ring3": ["002381.SZ", "002224.SZ", "300375.SZ", "002068.SZ"],
        "us_peers": ["GT"],
    },
    "MA0": {
        "name": "甲醇", "group": "HIGH", "driver": "MA0",
        "ring1_logic": "煤制甲醇及甲醇单品核心生产龙头",
        "ring2_logic": "MTO外购甲醇制烯烃成本敏感厂及乙烷/油头替代路线受益股",
        "ring3_logic": "煤化工工程、气化设备及边缘小醇醚概念股",
        "ring1": ["600989.SH", "600426.SH", "600256.SH", "601898.SH", "000912.SZ"],
        "ring2": ["003022.SZ", "002648.SZ", "002493.SZ", "600346.SH", "600141.SH"],
        "ring3": ["002140.SZ", "603698.SH", "600844.SH", "600722.SH"],
    },
    "BU0": {
        "name": "沥青", "group": "HIGH", "driver": "BU0",
        "ring1_logic": "重交沥青及炼化沥青核心供应商",
        "ring2_logic": "防水卷材与路桥施工（沥青占防水卷材直接材料大头，成本敏感）",
        "ring3_logic": "边缘公路养护机械与区域路桥概念股",
        "ring1": ["600028.SH", "601857.SH", "300135.SZ", "002377.SZ"],
        "ring2": ["002271.SZ", "300737.SZ", "300715.SZ", "000498.SZ", "600039.SH"],
        "ring3": ["300210.SZ", "300103.SZ", "002307.SZ", "002628.SZ"],
    },
    "LE_F": {
        "name": "美活牛", "group": "HIGH", "driver": "LE_F",
        "ring1_logic": "国内肉牛牧场与乳肉一体化养殖代表",
        "ring2_logic": "蛋白替代链（国内禽肉、猪肉、肉制品及饲料龙头）",
        "ring3_logic": "边缘乳饮与区域乳业扩散股",
        "ring1": ["300106.SZ", "600419.SH", "600887.SH", "600597.SH"],
        "ring2": ["000895.SZ", "002299.SZ", "002746.SZ", "002311.SZ"],
        "ring3": ["002329.SZ", "002910.SZ", "002732.SZ", "002946.SZ"],
        "us_peers": ["TSN"],
    },
    "CU0": {
        "name": "沪铜", "group": "HIGH", "driver": "CU0", "alt_driver": "HG_F",
        "ring1_logic": "上游铜矿自产资源与冶炼龙头",
        "ring2_logic": "下游用铜成本敏感（空调电网漆包线）及铝代铜替代受益产业链",
        "ring3_logic": "边缘铜箔、电线电缆与小金属概念扩散股",
        "ring1": ["601899.SH", "603993.SH", "601168.SH", "000630.SZ", "000878.SZ", "600362.SH"],
        "ring2": ["000651.SZ", "000333.SZ", "600089.SH", "601609.SH", "002203.SZ", "600577.SH"],
        "ring3": ["600110.SH", "688388.SH", "600869.SH", "002276.SZ", "300697.SZ"],
        "us_peers": ["FCX", "SCCO"],
    },
    "AG0": {
        "name": "沪银", "group": "HIGH", "driver": "AG0", "alt_driver": "SI_F",
        "ring1_logic": "原生白银矿产及高银储量多金属龙头",
        "ring2_logic": "光伏银浆成本敏感及少银化/铜电镀无银替代（BC与HJT设备）",
        "ring3_logic": "边缘白银冶炼伴生与小市值贵金属扩散股",
        "ring1": ["000426.SZ", "000603.SZ", "000975.SZ", "600531.SH"],
        "ring2": ["688503.SH", "300842.SZ", "002079.SZ", "601012.SH", "600732.SH", "300751.SZ"],
        "ring3": ["002716.SZ", "002237.SZ", "601212.SH", "600961.SH"],
        "us_peers": ["PAAS", "HL"],
    },
    "SN0": {
        "name": "沪锡", "group": "HIGH", "driver": "SN0",
        "ring1_logic": "上游锡矿高自给率绝对龙头",
        "ring2_logic": "中游锡焊料与PCB电子装联成本传导链",
        "ring3_logic": "边缘小金属钨钽稀贵题材联动股",
        "ring1": ["000960.SZ", "000426.SZ", "600301.SH"],
        "ring2": ["301319.SZ", "300476.SZ", "002463.SZ", "600206.SH"],
        "ring3": ["301323.SZ", "002378.SZ", "000962.SZ", "002842.SZ"],
    },
    "AU0": {
        "name": "黄金", "group": "HIGH", "driver": "AU0", "alt_driver": "GC_F",
        "ring1_logic": "纯黄金开采主业核心龙头",
        "ring2_logic": "下游品牌金饰与高金价库存重估/消费抑制敏感链",
        "ring3_logic": "边缘珠宝加工与海外参股黄金概念股",
        "ring1": ["600547.SH", "600489.SH", "600988.SH", "000975.SZ", "002155.SZ"],
        "ring2": ["600612.SH", "002867.SZ", "002345.SZ", "600916.SH"],
        "ring3": ["603900.SH", "301177.SZ", "002574.SZ", "300139.SZ"],
        "us_peers": ["NEM", "RGLD", "AEM"],
    },
    "EC0": {
        "name": "欧线集运", "group": "HIGH", "driver": "EC0", "proxy_10y": "BDI",
        "ring1_logic": "集装箱干线船东与集运直接弹性龙头",
        "ring2_logic": "高货柜占比出海家居制造（海运费敏感）及跨境货代物流",
        "ring3_logic": "边缘港口、集装箱制造及内贸散货航运股",
        "ring1": ["601919.SH", "601866.SH", "601083.SH", "603565.SH"],
        "ring2": ["300729.SZ", "603661.SH", "301061.SZ", "301376.SZ", "603128.SH", "601156.SH"],
        "ring3": ["000039.SZ", "601022.SH", "601975.SH", "000520.SZ", "600798.SH"],
        "us_peers": ["MATX"],
    },
    "AL0": {
        "name": "沪铝", "group": "HIGH", "driver": "AL0", "alt_driver": "ALI_F",
        "ring1_logic": "上游电解铝产能与绿电铝核心龙头",
        "ring2_logic": "中游铝加工、光伏边框、汽车轻量化与铝代铜传导股",
        "ring3_logic": "边缘再生铝、铝型材与小铝加工题材股",
        "ring1": ["601600.SH", "000807.SZ", "002532.SZ", "000933.SZ", "600219.SH"],
        "ring2": ["601677.SH", "002540.SZ", "002988.SZ", "003038.SZ", "600673.SH"],
        "ring3": ["601388.SH", "002996.SZ", "605208.SH", "002160.SZ", "002578.SZ"],
        "us_peers": ["AA", "CENX"],
    },
    "PL_F": {
        "name": "铂金", "group": "HIGH", "driver": "PL_F", "note": "10Y=84.85%紧贴85%阈值",
        "ring1_logic": "国内铂族金属回收与贵金属催化核心企业",
        "ring2_logic": "尾气催化剂与氢能燃料电池链（含铂钯互替需求弹性）",
        "ring3_logic": "边缘氢能概念扩散股",
        "ring1": ["600459.SH", "301026.SZ", "688269.SH"],
        "ring2": ["000581.SZ", "688021.SH", "300816.SZ", "688339.SH", "000338.SZ"],
        "ring3": ["000723.SZ", "002733.SZ", "300471.SZ", "002639.SZ"],
        "us_peers": ["SBSW"],
    },
    # --- LOW GROUP ---
    "FG0": {
        "name": "玻璃", "group": "LOW", "driver": "FG0",
        "ring1_logic": "浮法平板玻璃核心生产龙头",
        "ring2_logic": "下游汽车玻璃与光伏玻璃深加工（原片成本敏感及组件关联）",
        "ring3_logic": "边缘特种玻璃与石英概念扩散股",
        "ring1": ["601636.SH", "000012.SZ", "600586.SH", "600819.SH"],
        "ring2": ["600660.SH", "601865.SH", "002623.SZ", "600876.SH", "002571.SZ"],
        "ring3": ["300093.SZ", "300160.SZ", "600293.SH", "002613.SZ", "600207.SH"],
    },
    "SA0": {
        "name": "纯碱", "group": "LOW", "driver": "SA0",
        "ring1_logic": "天然碱/联碱/氨碱纯碱核心龙头",
        "ring2_logic": "下游光伏浮法玻璃与碳酸锂用碱（纯碱跌价直接压低成本）",
        "ring3_logic": "边缘小规模化工与盐化工扩散股",
        "ring1": ["000683.SZ", "600328.SH", "600409.SH", "000822.SZ", "603299.SH"],
        "ring2": ["601865.SH", "601636.SH", "000792.SZ", "603260.SH"],
        "ring3": ["603077.SH", "002274.SZ", "600929.SH", "002539.SZ"],
    },
    "AO0": {
        "name": "氧化铝", "group": "LOW", "driver": "AO0",
        "ring1_logic": "高氧化铝自给率及海外矿铝一体龙头（跌价先受损，涨价最受益）",
        "ring2_logic": "低自给率/纯外购氧化铝电解铝厂（氧化铝暴跌期间吨铝利润暴增）",
        "ring3_logic": "边缘氧化铝粉、铝氟化工及铝箔概念股",
        "ring1": ["601600.SH", "600219.SH", "002532.SZ"],
        "ring2": ["000807.SZ", "000933.SZ", "000612.SZ", "600595.SH"],
        "ring3": ["603978.SH", "600727.SH", "002379.SZ", "600673.SH"],
    },
    "PS0": {
        "name": "多晶硅", "group": "LOW", "driver": "PS0",
        "ring1_logic": "多晶硅/硅料纯正头部生产商",
        "ring2_logic": "下游电池组件与逆变器（低硅料压低LCOE并推动装机放量）",
        "ring3_logic": "边缘硅料还原炉、冷氢化设备及切片辅材股",
        "ring1": ["600438.SH", "688303.SH", "600089.SH", "603185.SH"],
        "ring2": ["601012.SH", "688223.SH", "002459.SZ", "688599.SH", "688472.SH", "300274.SZ"],
        "ring3": ["300316.SZ", "600481.SH", "002006.SZ", "601908.SH"],
        "us_peers": ["FSLR", "ENPH"],
    },
    "LH0": {
        "name": "生猪", "group": "LOW", "driver": "LH0", "proxy_10y": "HOG_SPOT",
        "ring1_logic": "生猪养殖头部规模化出栏龙头",
        "ring2_logic": "滞后6至12个月补栏受益：猪用动保疫苗、饲料与屠宰肉制品",
        "ring3_logic": "边缘转基因概念及小体量养猪困境扩散股",
        "ring1": ["002714.SZ", "300498.SZ", "603477.SH", "605296.SH", "600975.SH"],
        "ring2": ["600201.SH", "300119.SZ", "688526.SH", "002311.SZ", "000895.SZ"],
        "ring3": ["000702.SZ", "000735.SZ", "000860.SZ", "002124.SZ", "603363.SH"],
    },
    "SH0": {
        "name": "烧碱", "group": "LOW", "driver": "SH0",
        "ring1_logic": "氯碱烧碱与自备电液碱核心厂商",
        "ring2_logic": "下游氧化铝焙烧、粘胶短纤与造纸用碱成本受益股",
        "ring3_logic": "边缘农药中间体、电子湿化学品及小氯碱股",
        "ring1": ["601678.SH", "600618.SH", "002092.SZ", "601216.SH", "601568.SH"],
        "ring2": ["601600.SH", "000807.SZ", "600409.SH", "002078.SZ"],
        "ring3": ["600273.SH", "600389.SH", "603078.SH", "002748.SZ"],
    },
    "PA_F": {
        "name": "钯金", "group": "LOW", "driver": "PA_F",
        "ring1_logic": "国内铂钯贵金属回收与冶炼核心",
        "ring2_logic": "汽油车尾气三元催化剂成本敏感股（钯金暴跌压低催化剂BOM，引发铂返替钯）",
        "ring3_logic": "边缘废旧资源回收与有色钴镍扩散股",
        "ring1": ["600459.SH", "301026.SZ", "688269.SH"],
        "ring2": ["000581.SZ", "688021.SH", "300816.SZ", "300680.SZ", "002126.SZ"],
        "ring3": ["301500.SZ", "002340.SZ", "603799.SH", "300618.SZ"],
        "us_peers": ["SBSW"],
    },
    "SI0": {
        "name": "工业硅", "group": "LOW", "driver": "SI0",
        "ring1_logic": "金属工业硅与硅基一体化绝对龙头",
        "ring2_logic": "下游有机硅硅烷偶联剂与密封胶（工业硅跌价释放深加工利润）",
        "ring3_logic": "边缘硅化工、气凝胶与电子硅概念股",
        "ring1": ["603260.SH", "300821.SZ", "600596.SH", "600141.SH"],
        "ring2": ["605366.SH", "605399.SH", "300727.SZ", "300019.SZ"],
        "ring3": ["300610.SZ", "002909.SZ", "000830.SZ", "688126.SH"],
    },
    "SM0": {
        "name": "锰硅", "group": "LOW", "driver": "SM0",
        "ring1_logic": "硅锰合金、电解锰及锰系电池正极前驱核心",
        "ring2_logic": "下游钢铁炼钢脱氧合金剂成本受益股",
        "ring3_logic": "边缘小金属与矿产勘探题材股",
        "ring1": ["600295.SH", "002125.SZ", "600367.SH"],
        "ring2": ["600019.SH", "000932.SZ", "600282.SH", "002057.SZ"],
        "ring3": ["000758.SZ", "002428.SZ", "600399.SH", "002978.SZ"],
    },
    "V0": {
        "name": "PVC", "group": "LOW", "driver": "V0",
        "ring1_logic": "电石法与乙烯法PVC核心产能龙头",
        "ring2_logic": "下游PVC塑料管材、型材与PVC地板（直接受益树脂降价）",
        "ring3_logic": "边缘烧碱副产、电石与老牌氯碱概念股",
        "ring1": ["002092.SZ", "600075.SH", "601216.SH", "601568.SH", "000635.SZ"],
        "ring2": ["002372.SZ", "002641.SZ", "003011.SZ", "300599.SZ"],
        "ring3": ["600618.SH", "600273.SH", "600295.SH", "002748.SZ"],
    },
    "HC0": {
        "name": "热卷", "group": "LOW", "driver": "HC0",
        "ring1_logic": "板材热轧卷板主流大型钢企",
        "ring2_logic": "下游造船、重卡挂车、工程机械与重型装备（钢板成本占BOM极高）",
        "ring3_logic": "边缘高弹性区域钢企与特钢题材股",
        "ring1": ["600019.SH", "000932.SZ", "600282.SH", "600782.SH", "000825.SZ"],
        "ring2": ["600150.SH", "301039.SZ", "600031.SH", "600320.SH", "600875.SH"],
        "ring3": ["600808.SH", "000898.SZ", "601003.SH", "000761.SZ", "600399.SH"],
        "us_peers": ["NUE", "STLD"],
    },
    "RB0": {
        "name": "螺纹钢", "group": "LOW", "driver": "RB0",
        "ring1_logic": "建筑长材螺纹钢高弹性民营/区域钢企",
        "ring2_logic": "下游钢结构制造与焊接钢管加工（钢价下行+加工费刚性受益）",
        "ring3_logic": "边缘低价亏损钢铁重组题材股",
        "ring1": ["600507.SH", "002110.SZ", "000717.SZ", "600126.SH", "000709.SZ"],
        "ring2": ["002541.SZ", "600496.SH", "002135.SZ", "601686.SH", "002443.SZ"],
        "ring3": ["601005.SH", "600307.SH", "600569.SH", "600117.SH", "600231.SH"],
        "us_peers": ["CLF"],
    },
    "JD0": {
        "name": "鸡蛋", "group": "LOW", "driver": "JD0",
        "ring1_logic": "蛋鸡种苗与规模化禽养殖核心股",
        "ring2_logic": "下游烘焙面包（鸡蛋原料成本敏感）及禽用饲料龙头",
        "ring3_logic": "边缘肉禽屠宰与综合食品农牧概念股",
        "ring1": ["002458.SZ", "002234.SZ", "300967.SZ", "300761.SZ"],
        "ring2": ["603866.SH", "300973.SZ", "002557.SZ", "002311.SZ", "603609.SH"],
        "ring3": ["002982.SZ", "002321.SZ", "603668.SH", "603336.SH"],
    },
    "NI0": {
        "name": "沪镍", "group": "LOW", "driver": "NI0",
        "ring1_logic": "红土镍矿湿法/火法冶炼与前驱体一体化龙头",
        "ring2_logic": "中游不锈钢冷轧加工与高镍三元正极材料（低镍价降低高镍电池成本）",
        "ring3_logic": "边缘镍资源概念与特种合金题材股",
        "ring1": ["603799.SH", "002340.SZ", "603568.SH", "600711.SH", "300919.SZ"],
        "ring2": ["000825.SZ", "603995.SH", "002318.SZ", "688005.SH", "300073.SZ"],
        "ring3": ["600490.SH", "601168.SH", "300402.SZ", "600399.SH"],
    },
    "SR0": {
        "name": "白糖", "group": "LOW", "driver": "SR0",
        "ring1_logic": "国内甘蔗/甜菜制糖核心龙头",
        "ring2_logic": "下游软饮料（食糖成本占比高）及代糖甜味剂替代品链",
        "ring3_logic": "边缘功能糖醇与植物提取物概念股",
        "ring1": ["600737.SH", "000833.SZ", "600251.SH"],
        "ring2": ["605499.SH", "605337.SH", "000848.SZ", "002597.SZ", "002286.SZ"],
        "ring3": ["605016.SH", "301206.SZ", "605077.SH", "300138.SZ"],
    },
    "SP0": {
        "name": "纸浆", "group": "LOW", "driver": "SP0",
        "ring1_logic": "林浆纸一体化及自制浆大厂（浆价低谷压制资产盈利，反转先弹性）",
        "ring2_logic": "纯外购木浆生活用纸与特种纸（浆价暴跌毛利率直接爆发）",
        "ring3_logic": "边缘废纸箱板、印刷及纸尿裤下游概念股",
        "ring1": ["002078.SZ", "600963.SH", "600308.SH", "600103.SH"],
        "ring2": ["002511.SZ", "603733.SH", "605007.SH", "605377.SH", "600966.SH"],
        "ring3": ["002067.SZ", "600235.SH", "600793.SH", "600356.SH", "605009.SH"],
    },
    "I0": {
        "name": "铁矿石", "group": "LOW", "driver": "I0",
        "ring1_logic": "国内铁矿采选与海外矿权核心公司",
        "ring2_logic": "下游长流程高炉钢厂（矿价暴跌但钢价滞跌期扩大利润剪刀差）",
        "ring3_logic": "边缘铁精粉伴生矿与矿山选矿设备股",
        "ring1": ["601969.SH", "000655.SZ", "000923.SZ", "001203.SZ", "601121.SH"],
        "ring2": ["600019.SH", "000932.SZ", "600282.SH", "000708.SZ", "002318.SZ"],
        "ring3": ["002978.SZ", "000762.SZ", "300818.SZ", "300837.SZ"],
    },
    "C0": {
        "name": "国内玉米", "group": "LOW", "driver": "C0",
        "ring1_logic": "玉米规模种植与杂交玉米种业龙头",
        "ring2_logic": "玉米深加工味精氨基酸与养殖饲料（低玉米价格压低原料成本）",
        "ring3_logic": "边缘小市值种子与转基因题材扩散股",
        "ring1": ["600598.SH", "002041.SZ", "000998.SZ", "600313.SH", "601952.SH"],
        "ring2": ["600873.SH", "600866.SH", "000930.SZ", "002311.SZ", "000876.SZ"],
        "ring3": ["600371.SH", "600354.SH", "000713.SZ", "300189.SZ"],
    },
}


def fetch_cn_future(sym: str) -> tuple[str, pd.Series | None]:
    for _ in range(3):
        try:
            df = ak.futures_zh_daily_sina(symbol=sym)
            if df is None or df.empty:
                return sym, None
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            s = df.set_index("date")["close"].dropna().sort_index()
            s = s[~s.index.duplicated(keep="last")]
            return sym, s[s.index <= END_DT]
        except Exception:
            continue
    return sym, None


def compute_percentiles(s: pd.Series) -> dict:
    s = s.dropna().sort_index()
    n = len(s)
    last_dt = s.index[-1]
    yrs = round((last_dt - s.index[0]).days / 365.25, 2)
    # Use calendar-year slice AND trading-day slice
    s10_cal = s.loc[last_dt - pd.DateOffset(years=10):]
    s5_cal = s.loc[last_dt - pd.DateOffset(years=5):]
    s3_cal = s.loc[last_dt - pd.DateOffset(years=3):]
    p10_2520 = float(s.iloc[-min(n, 2520):].rank(pct=True).iloc[-1] * 100.0)
    p5_1260 = float(s.iloc[-min(n, 1260):].rank(pct=True).iloc[-1] * 100.0)
    p10_cal = float(s10_cal.rank(pct=True).iloc[-1] * 100.0)
    p5_cal = float(s5_cal.rank(pct=True).iloc[-1] * 100.0)
    p3_cal = float(s3_cal.rank(pct=True).iloc[-1] * 100.0)
    pall = float(s.rank(pct=True).iloc[-1] * 100.0)
    ret20 = float((s.iloc[-1] / s.iloc[-21] - 1.0) * 100.0) if n >= 22 else None
    ret60 = float((s.iloc[-1] / s.iloc[-61] - 1.0) * 100.0) if n >= 62 else None
    ma20 = float(s.iloc[-20:].mean()) if n >= 20 else None
    ma60 = float(s.iloc[-60:].mean()) if n >= 60 else None
    return {
        "start": str(s.index[0])[:10], "end": str(last_dt)[:10], "n": int(n), "yrs": yrs,
        "close": round(float(s.iloc[-1]), 2),
        "p10y_2520": round(p10_2520, 1), "p5y_1260": round(p5_1260, 1),
        "p10y_cal": round(p10_cal, 1), "p5y_cal": round(p5_cal, 1), "p3y_cal": round(p3_cal, 1),
        "pall": round(pall, 1),
        "ret20_pct": round(ret20, 2) if ret20 is not None else None,
        "ret60_pct": round(ret60, 2) if ret60 is not None else None,
        "above_ma20": bool(float(s.iloc[-1]) > ma20) if ma20 is not None else None,
        "above_ma60": bool(float(s.iloc[-1]) > ma60) if ma60 is not None else None,
    }


def main():
    print("[1/5] Fetching 58 CN futures in parallel via AKShare...")
    cn_series = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(fetch_cn_future, sym) for sym in CN_FUTURES_UNIVERSE]
        for f in concurrent.futures.as_completed(futs):
            sym, s = f.result()
            if s is not None and len(s) > 30:
                cn_series[sym] = s
    print(f"  Fetched {len(cn_series)}/{len(CN_FUTURES_UNIVERSE)} CN futures.")

    # Save CN futures full history for causal rolling window (2005+ where available)
    pd.DataFrame(cn_series).sort_index().to_parquet(CACHE_DIR / "cn_futures_close.parquet")

    print("[2/5] Loading 24 Global futures + ES_F from local commodities parquet...")
    global_series = {}
    for sym in list(GLOBAL_FUTURES_UNIVERSE.keys()) + ["ES_F"]:
        p = GLOBAL_COMM_DIR / f"{sym}.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        idx = df.index if isinstance(df.index, pd.DatetimeIndex) else pd.to_datetime(df["date"])
        s = pd.Series(pd.to_numeric(df["close"], errors="coerce").values, index=idx).dropna().sort_index()
        s = s[~s.index.duplicated(keep="last")]
        if sym == "CL_F":
            s = s.where(s > 0.0, np.nan)
        global_series[sym] = s[s.index <= END_DT]
    pd.DataFrame(global_series).sort_index().to_parquet(CACHE_DIR / "global_futures_close.parquet")

    # HOG_SPOT (10Y weekly) & BDI (10Y daily)
    hog = ak.index_hog_spot_price()
    hog["date"] = pd.to_datetime(hog["日期"])
    hog["spot"] = pd.to_numeric(hog["成交均价"], errors="coerce").fillna(pd.to_numeric(hog["指数"], errors="coerce"))
    hog_s = hog.set_index("date")["spot"].dropna().sort_index()
    hog_s = hog_s[~hog_s.index.duplicated(keep="last")][lambda x: x.index <= END_DT]
    hog_s.to_frame("HOG_SPOT").to_parquet(CACHE_DIR / "hog_spot.parquet")

    bdi = ak.macro_shipping_bdi()
    bdi["date"] = pd.to_datetime(bdi["日期"])
    bdi["val"] = pd.to_numeric(bdi["最新值"], errors="coerce")
    bdi_s = bdi.set_index("date")["val"].dropna().sort_index()
    bdi_s = bdi_s[~bdi_s.index.duplicated(keep="last")][lambda x: x.index <= END_DT]
    bdi_s.to_frame("BDI").to_parquet(CACHE_DIR / "bdi.parquet")

    print("[3/5] Screening all 82+ futures + proxies for extreme percentiles...")
    screen_rows = []
    for sym, s in sorted(cn_series.items()):
        nm, cat = CN_FUTURES_UNIVERSE[sym]
        st = compute_percentiles(s)
        is_hi = (st["p10y_2520"] >= 85.0) or (st["p5y_1260"] >= 85.0)
        is_lo = (st["p10y_2520"] <= 10.0) or (st["p5y_1260"] <= 5.0)
        screen_rows.append({"mkt": "CN", "sym": sym, "name": nm, "cat": cat, "extreme": "HIGH" if is_hi else ("LOW" if is_lo else "NEUTRAL"), **st})
    for sym, (nm, cat) in GLOBAL_FUTURES_UNIVERSE.items():
        if sym not in global_series:
            continue
        st = compute_percentiles(global_series[sym].dropna())
        is_hi = (st["p10y_2520"] >= 85.0) or (st["p5y_1260"] >= 85.0)
        is_lo = (st["p10y_2520"] <= 10.0) or (st["p5y_1260"] <= 5.0)
        flag = "HIGH" if is_hi else ("LOW" if is_lo else ("HIGH_BORDER" if sym == "PL_F" else "NEUTRAL"))
        screen_rows.append({"mkt": "GLOBAL", "sym": sym, "name": nm, "cat": cat, "extreme": flag, **st})
    for sym, nm, s in [("HOG_SPOT", "中国生猪现货(周)", hog_s), ("BDI", "波罗的海干散货BDI", bdi_s)]:
        st = compute_percentiles(s)
        is_hi = (st["p10y_cal"] >= 85.0) or (st["p5y_cal"] >= 85.0)
        is_lo = (st["p10y_cal"] <= 10.0) or (st["p5y_cal"] <= 5.0)
        screen_rows.append({"mkt": "PROXY", "sym": sym, "name": nm, "cat": "现货代理", "extreme": "HIGH" if is_hi else ("LOW" if is_lo else "NEUTRAL"), **st})

    scr_df = pd.DataFrame(screen_rows)
    scr_df.to_csv(OUT_DIR / "commodity_extreme_screen_all.csv", index=False)
    with open(OUT_DIR / "commodity_extreme_screen_all.json", "w", encoding="utf-8") as f:
        json.dump(screen_rows, f, ensure_ascii=False, indent=2)

    print("[4/5] Verifying all 3-ring A-share + US stock tickers against local parquets...")
    all_a_tickers = sorted({tk for spec in THREE_RING_MAP.values() for r in ("ring1", "ring2", "ring3") for tk in spec[r]})
    all_us_tickers = sorted({tk for spec in THREE_RING_MAP.values() for tk in spec.get("us_peers", [])})

    # Load code-name map
    nm_df = ak.stock_info_a_code_name()
    code_to_name = dict(zip(nm_df["code"], nm_df["name"]))

    sub_a = pd.read_parquet(
        A_DAILY_PATH,
        columns=["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "qfq_factor"],
        filters=[("ticker", "in", all_a_tickers)],
    )
    sub_a["date"] = pd.to_datetime(sub_a["date"])
    sub_a = sub_a[(sub_a["date"] >= START_DT) & (sub_a["date"] <= END_DT)].sort_values(["ticker", "date"])
    ratio = sub_a["adj_close"] / sub_a["close"].replace(0, np.nan)
    sub_a["adj_open"] = sub_a["open"] * ratio
    sub_a["adj_high"] = sub_a["high"] * ratio
    sub_a["adj_low"] = sub_a["low"] * ratio

    a_close = sub_a.pivot_table(index="date", columns="ticker", values="adj_close", aggfunc="last").sort_index()
    a_open = sub_a.pivot_table(index="date", columns="ticker", values="adj_open", aggfunc="last").sort_index()
    a_raw_o = sub_a.pivot_table(index="date", columns="ticker", values="open", aggfunc="last").sort_index()
    a_raw_h = sub_a.pivot_table(index="date", columns="ticker", values="high", aggfunc="last").sort_index()
    a_raw_l = sub_a.pivot_table(index="date", columns="ticker", values="low", aggfunc="last").sort_index()
    a_raw_c = sub_a.pivot_table(index="date", columns="ticker", values="close", aggfunc="last").sort_index()

    # Exact one-word limit-up at open flag (yizi_up_open):
    # open == high == low == close (or open == low and open >= prev_adj_close * (1 + thresh))
    # Compute open gap relative to previous trading day's adj_close
    prev_adj_c = a_close.ffill().shift(1)
    open_ret = a_open / prev_adj_c - 1.0
    is_yizi = pd.DataFrame(False, index=a_close.index, columns=a_close.columns)
    for tk in a_close.columns:
        th = 0.195 if tk.startswith(("300", "301", "688", "689")) else (0.295 if tk.startswith(("8", "9", "4")) else 0.095)
        eq_ohlc = (a_raw_o[tk] - a_raw_l[tk]).abs() <= 1e-4
        eq_hl = (a_raw_h[tk] - a_raw_l[tk]).abs() <= 1e-4
        is_yizi[tk] = eq_ohlc & eq_hl & (open_ret[tk] >= th)

    is_yizi_down = pd.DataFrame(False, index=a_close.index, columns=a_close.columns)
    for tk in a_close.columns:
        th = -0.195 if tk.startswith(("300", "301", "688", "689")) else (-0.295 if tk.startswith(("8", "9", "4")) else -0.095)
        eq_ohlc = (a_raw_o[tk] - a_raw_h[tk]).abs() <= 1e-4
        eq_hl = (a_raw_h[tk] - a_raw_l[tk]).abs() <= 1e-4
        is_yizi_down[tk] = eq_ohlc & eq_hl & (open_ret[tk] <= th)

    a_close.to_parquet(CACHE_DIR / "a_stocks_close.parquet")
    a_open.to_parquet(CACHE_DIR / "a_stocks_open.parquet")
    is_yizi.to_parquet(CACHE_DIR / "a_stocks_yizi_up.parquet")
    is_yizi_down.to_parquet(CACHE_DIR / "a_stocks_yizi_down.parquet")

    # CSI 300 from panel_v2 (exact official index OHLC)
    p2 = pd.read_parquet(PANEL_V2_PATH, columns=["date", "csi300_open", "csi300_close"])
    p2["date"] = pd.to_datetime(p2["date"])
    p2 = p2[(p2["date"] >= START_DT) & (p2["date"] <= END_DT)].set_index("date").sort_index()
    p2.to_parquet(CACHE_DIR / "csi300.parquet")

    # US peers
    if all_us_tickers:
        us_df = pd.read_parquet(
            US_DAILY_PATH,
            columns=["date", "ticker", "open", "close", "adj_close"],
            filters=[("ticker", "in", all_us_tickers)],
        )
        us_df["date"] = pd.to_datetime(us_df["date"])
        us_df = us_df[(us_df["date"] >= START_DT) & (us_df["date"] <= END_DT)]
        us_close = us_df.pivot_table(index="date", columns="ticker", values="adj_close", aggfunc="last").sort_index()
        us_close.to_parquet(CACHE_DIR / "us_stocks_close.parquet")
    else:
        us_close = pd.DataFrame()

    print("[5/5] Auditing & writing three_ring_mapping.json...")
    ticker_audit = {}
    bad_tickers = []
    for tk in all_a_tickers:
        nm = code_to_name.get(tk[:6], "MISSING")
        s = a_close[tk].dropna() if tk in a_close.columns else pd.Series(dtype=float)
        st_dt = str(s.index.min())[:10] if len(s) else None
        en_dt = str(s.index.max())[:10] if len(s) else None
        cov = round(len(s) / len(p2.loc[s.index.min():END_DT]) * 100.0, 1) if len(s) else 0.0
        ticker_audit[tk] = {"name": nm, "start": st_dt, "end": en_dt, "n": int(len(s)), "cov_pct": cov}
        if nm == "MISSING" or "ST" in nm or "退" in nm or len(s) < 200 or en_dt < "2026-11-20":
            bad_tickers.append((tk, nm, st_dt, en_dt, len(s)))
    if bad_tickers:
        raise RuntimeError(f"Bad/ST/Missing tickers found: {bad_tickers}")

    mapping_out = {
        "as_of_date": "2026-11-24",
        "total_commodities_mapped": len(THREE_RING_MAP),
        "total_unique_a_tickers": len(all_a_tickers),
        "total_unique_us_tickers": len(all_us_tickers),
        "ticker_audit": ticker_audit,
        "commodities": {},
    }
    scr_idx = scr_df.set_index("sym").to_dict("index")
    for sym, spec in THREE_RING_MAP.items():
        scr_info = scr_idx.get(sym, {})
        enriched = dict(spec)
        enriched["screen"] = scr_info
        for r in ("ring1", "ring2", "ring3"):
            enriched[f"{r}_named"] = [{"ticker": tk, "name": ticker_audit[tk]["name"], "start": ticker_audit[tk]["start"]} for tk in spec[r]]
        mapping_out["commodities"][sym] = enriched

    with open(OUT_DIR / "three_ring_mapping.json", "w", encoding="utf-8") as f:
        json.dump(mapping_out, f, ensure_ascii=False, indent=2)

    print(f"DONE Step 1: mapped {len(THREE_RING_MAP)} extreme commodities across {len(all_a_tickers)} verified A-share tickers!")
    print("High group count:", sum(1 for v in THREE_RING_MAP.values() if v["group"] == "HIGH"))
    print("Low group count:", sum(1 for v in THREE_RING_MAP.values() if v["group"] == "LOW"))


if __name__ == "__main__":
    main()
