#!/usr/bin/env python3
"""
W1_11: 2026Q3 飞书172篇财报库与美股 >250亿美元 实时选股底座提取器
生成:
1. /tmp/us_earn_macro_bt_20261109/q3_2026/feishu_q3_172_inventory.json
2. /tmp/us_earn_macro_bt_20261109/q3_2026/us_live_2026q3_candidates.parquet
"""

import os
import sys
import json
import time
import re
import subprocess
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import openpyxl
import yfinance as yf

# Paths
OUT_DIR = "/tmp/us_earn_macro_bt_20261109/q3_2026"
FEISHU_JSON_PATH = os.path.join(OUT_DIR, "feishu_q3_172_inventory.json")
CANDIDATES_PARQUET_PATH = os.path.join(OUT_DIR, "us_live_2026q3_candidates.parquet")
YF_CACHE_PATH = os.path.join(OUT_DIR, ".yf_cache.json")

UNIVERSE_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_price_db/universe.csv"
DAILY_PATH = "/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/us_price_db/all_daily.parquet"
JUMP_EXCEL_PATH = "/Users/huaichuaibeimeng/Desktop/Track/1_活表/1_选股_美股2026中报财报日涨跌.xlsx"
FEISHU_TOKEN_SCRIPT = "/Users/huaichuaibeimeng/.claude/session-remote/feishu_token.py"

FEISHU_SPACE_ID = "7702350621394947083"
FEISHU_PARENT_NODE = "N6v9wJ59BioybdkYOaucbl9HnUf"

KNOWN_CHINA_TICKERS = {
    'BABA', 'PDD', 'JD', 'NTES', 'BIDU', 'TCOM', 'BEKE', 'FUTU', 'ZTO', 'YUMC',
    'HTHT', 'TME', 'LI', 'XPEV', 'NIO', 'EDU', 'BZ', 'TAL', 'BILI', 'GDS',
    'KC', 'ATHM', 'QFIN', 'LU', 'WB', 'DOYU', 'HUYA', 'IQ', 'RLX', 'EH',
    'LKNCY', 'GOTU', 'TUYA', 'YSG', 'CAN', 'MNSO', 'ZLAB', 'DADA', 'FINV',
    'BGNE', 'VNET', 'VIPS', 'NOAH', 'YMM', 'DAO', 'ATAT', 'LIZI', 'BEST'
}


def step1_fetch_feishu_inventory():
    print("\n" + "=" * 60)
    print("Step 1: 抓取飞书 2026Q3 财报季专区 172 篇文档目录 (只读)")
    print("=" * 60)

    # 1. Get token
    cmd = ["python3", FEISHU_TOKEN_SCRIPT]
    tok = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    if not tok:
        raise RuntimeError("无法获取飞书 access_token，请检查 feishu_token.py")

    all_nodes = []
    page_token = ""
    has_more = True
    page = 1

    while has_more:
        url = f"https://open.feishu.cn/open-apis/wiki/v2/spaces/{FEISHU_SPACE_ID}/nodes?parent_node_token={FEISHU_PARENT_NODE}&page_size=50"
        if page_token:
            url += f"&page_token={page_token}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                if data.get("code") != 0:
                    raise RuntimeError(f"飞书 API 报错: {data}")
                items = data.get("data", {}).get("items", [])
                all_nodes.extend(items)
                has_more = data.get("data", {}).get("has_more", False)
                page_token = data.get("data", {}).get("page_token", "")
                print(f"  第 {page} 页成功拉取 {len(items)} 个节点 (累计 {len(all_nodes)} 个)")
                page += 1
        except Exception as e:
            print(f"  拉取重试中: {e}")
            time.sleep(2)
            continue

    parsed_inventory = []
    for n in all_nodes:
        title = n.get("title", "").strip()
        m_ticker = re.search(r'\(([^)]+)\)', title)
        ticker = m_ticker.group(1).strip() if m_ticker else ""

        # 市场分类
        if re.match(r'^\d{6}$', ticker):
            market = "A_SHARE"
        elif ticker.endswith(".HK"):
            market = "HK"
        elif ticker.endswith(".T"):
            market = "JP"
        elif ticker.endswith(".KS") or ticker.endswith(".KQ"):
            market = "KR"
        elif ticker.endswith(".TW") or ticker.endswith(".TWO"):
            market = "TW"
        else:
            market = "US"

        m_tag = re.search(r'·\s*(Beat|Miss|Inline)\s*·', title, re.IGNORECASE)
        beat_miss = m_tag.group(1).capitalize() if m_tag else None

        m_date = re.search(r'·\s*(2026\.\d{2}\.\d{2})', title)
        report_date = m_date.group(1).replace(".", "-") if m_date else None

        parts = [p.strip() for p in title.split("·")]
        desc = parts[-1] if len(parts) >= 4 else ""

        parsed_inventory.append({
            "title": title,
            "ticker": ticker,
            "market": market,
            "beat_miss": beat_miss,
            "report_date": report_date,
            "price_reaction_desc": desc,
            "node_token": n.get("node_token"),
            "obj_token": n.get("obj_token"),
            "obj_type": n.get("obj_type"),
            "url": n.get("url"),
            "node_create_time": n.get("node_create_time"),
            "obj_edit_time": n.get("obj_edit_time")
        })

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(FEISHU_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(parsed_inventory, f, indent=2, ensure_ascii=False)

    print(f"✓ 飞书 2026Q3 节点盘点完成，共保存 {len(parsed_inventory)} 篇至 {FEISHU_JSON_PATH}")
    m_counts = pd.Series([x["market"] for x in parsed_inventory]).value_counts().to_dict()
    print(f"  各市场分布: {m_counts}")
    return parsed_inventory


def step2_load_jumps():
    print("\n" + "=" * 60)
    print("Step 2: 只读读取 1_选股_美股2026中报财报日涨跌.xlsx 中的 26Q3 / 26Q2 财报跳涨记录")
    print("=" * 60)
    wb = openpyxl.load_workbook(JUMP_EXCEL_PATH, read_only=True, data_only=True)
    ws = wb['10_财报日涨跌全表']
    rows = list(ws.iter_rows(min_row=4, values_only=True))
    headers = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
    data = rows[1:]
    wb.close()

    df_j = pd.DataFrame(data, columns=headers)
    df_j = df_j[df_j['口径'] == '财报跳涨']

    jumps_dict = {}
    for _, row in df_j.iterrows():
        t = str(row['代码']).strip().upper()
        season = str(row['财报季']).strip() if row['财报季'] else ""
        if season not in ('26Q3', '26Q2'):
            continue

        if t not in jumps_dict:
            jumps_dict[t] = {
                'has_jump_26q3': False,
                'jump_date_26q3': None,
                'jump_pct_26q3': None,
                'jump_timing_26q3': None,
                'jump_return_since_26q3': None,
                'has_jump_26q2': False,
                'jump_date_26q2': None,
                'jump_pct_26q2': None,
                'jump_timing_26q2': None,
                'jump_return_since_26q2': None,
                'jump_sector_tag': row['板块Tag'],
                'jump_outcome': row['结局'],
            }

        jump_pct = float(row['当日涨跌%']) if row['当日涨跌%'] is not None else None
        ret_since = float(row['跳涨后至今%']) if row['跳涨后至今%'] is not None else None
        jdate = str(row['跳涨日']).split()[0] if row['跳涨日'] else None
        timing = str(row['时点']).strip() if row['时点'] else None

        if season == '26Q3':
            jumps_dict[t]['has_jump_26q3'] = True
            jumps_dict[t]['jump_date_26q3'] = jdate
            jumps_dict[t]['jump_pct_26q3'] = jump_pct
            jumps_dict[t]['jump_timing_26q3'] = timing
            jumps_dict[t]['jump_return_since_26q3'] = ret_since
            if row['板块Tag']: jumps_dict[t]['jump_sector_tag'] = row['板块Tag']
            if row['结局']: jumps_dict[t]['jump_outcome'] = row['结局']
        elif season == '26Q2':
            if not jumps_dict[t]['has_jump_26q2'] or (jump_pct and jump_pct > (jumps_dict[t]['jump_pct_26q2'] or -999)):
                jumps_dict[t]['has_jump_26q2'] = True
                jumps_dict[t]['jump_date_26q2'] = jdate
                jumps_dict[t]['jump_pct_26q2'] = jump_pct
                jumps_dict[t]['jump_timing_26q2'] = timing
                jumps_dict[t]['jump_return_since_26q2'] = ret_since

    print(f"✓ 财报跳涨记录提取完成，涵盖标的数: {len(jumps_dict)}")
    q3_cnt = sum(1 for v in jumps_dict.values() if v['has_jump_26q3'])
    q2_cnt = sum(1 for v in jumps_dict.values() if v['has_jump_26q2'])
    print(f"  26Q3 财报跳涨标的数: {q3_cnt}, 26Q2 财报跳涨标的数: {q2_cnt}")
    return jumps_dict


def step3_prepare_universe(feishu_inventory):
    print("\n" + "=" * 60)
    print("Step 3: 构建美股候选宇宙 (>= 150亿美元 非中概 + 飞书Q3专区全量美股)")
    print("=" * 60)
    df_uni = pd.read_csv(UNIVERSE_PATH)
    ge_15b = df_uni[df_uni['market_cap'] >= 15e9].copy()

    # 排除中概股
    ge_15b_non_china = ge_15b[~ge_15b['ticker'].isin(KNOWN_CHINA_TICKERS)].copy()
    print(f"  本地 Universe 中 >= $15B 美股总数: {len(ge_15b)}，剔除中概后: {len(ge_15b_non_china)}")

    feishu_us = [x for x in feishu_inventory if x['market'] == 'US']
    feishu_us_dict = {x['ticker']: x for x in feishu_us}
    print(f"  飞书 Q3 专区美股标的数: {len(feishu_us)}")

    all_tickers = sorted(list(set(ge_15b_non_china['ticker'].tolist() + list(feishu_us_dict.keys()))))
    print(f"  合并后美股候选总量: {len(all_tickers)}")
    return all_tickers, feishu_us_dict, df_uni


def step4_compute_price_technicals(tickers):
    print("\n" + "=" * 60)
    print("Step 4: 计算日频技术指标 (最新价/过去半年/1年/2年/3年涨跌幅/最大回撤/波动率/缓涨时长/距52周高点)")
    print("=" * 60)

    # 读取本地 daily
    print(f"  正在从 {DAILY_PATH} 读取历史日频行情...")
    df_daily = pd.read_parquet(DAILY_PATH)
    df_daily['date'] = pd.to_datetime(df_daily['date'])
    df_daily = df_daily[df_daily['date'] <= '2026-11-06'].sort_values(['ticker', 'date'])

    available_tickers = set(df_daily['ticker'].unique())
    missing_tickers = [t for t in tickers if t not in available_tickers]
    print(f"  本地日频库匹配标的: {len(tickers) - len(missing_tickers)}，缺失标的: {len(missing_tickers)} ({missing_tickers})")

    # 针对缺失标的通过 yfinance 拉取 3 年日线
    extra_daily_list = []
    if missing_tickers:
        print(f"  正在通过 yfinance 补全 {len(missing_tickers)} 只缺失标的日线...")
        for mt in missing_tickers:
            try:
                tk = yf.Ticker(mt)
                hist = tk.history(period="3y")
                if len(hist) > 0:
                    hist = hist.reset_index()
                    hist['date'] = pd.to_datetime(hist['Date']).dt.tz_localize(None)
                    hist['ticker'] = mt
                    hist['close'] = hist['Close']
                    hist['high'] = hist['High']
                    hist['low'] = hist['Low']
                    hist['open'] = hist['Open']
                    hist['volume'] = hist['Volume']
                    hist = hist[hist['date'] <= '2026-11-06']
                    extra_daily_list.append(hist[['date', 'ticker', 'open', 'high', 'low', 'close', 'volume']])
            except Exception as e:
                print(f"    补全 {mt} 失败: {e}")

    if extra_daily_list:
        df_extra = pd.concat(extra_daily_list, ignore_index=True)
        df_daily = pd.concat([df_daily, df_extra], ignore_index=True).sort_values(['ticker', 'date'])

    # 针对每个 ticker 计算指标
    tech_results = {}
    grouped = df_daily[df_daily['ticker'].isin(tickers)].groupby('ticker')
    for t, group in grouped:
        group = group.sort_values('date').reset_index(drop=True)
        n = len(group)
        if n == 0:
            continue

        latest_close = float(group['close'].iloc[-1])
        latest_date = str(group['date'].iloc[-1]).split()[0]

        ret_6m = float(latest_close / group['close'].iloc[-126] - 1) if n >= 126 else None
        ret_1y = float(latest_close / group['close'].iloc[-252] - 1) if n >= 252 else None
        ret_2y = float(latest_close / group['close'].iloc[-504] - 1) if n >= 504 else None
        ret_3y = float(latest_close / group['close'].iloc[-756] - 1) if n >= 756 else None

        win_1y = group.tail(252) if n >= 252 else group
        high_52w = float(win_1y['high'].max() if 'high' in win_1y.columns else win_1y['close'].max())
        dist_52w = float((latest_close - high_52w) / high_52w) if high_52w > 0 else None

        closes_1y = win_1y['close'].values
        cummax = np.maximum.accumulate(closes_1y)
        drawdowns = (closes_1y - cummax) / cummax
        max_dd_1y = float(np.min(drawdowns)) if len(drawdowns) > 0 else None

        pct_chg = win_1y['close'].pct_change().dropna()
        vol_1y = float(pct_chg.std() * np.sqrt(252)) if len(pct_chg) > 20 else None

        # 缓涨时长 (截至 2026-11-06 连续站上 MA20 交易日数)
        ma20_series = group['close'].rolling(20).mean()
        above_ma20 = (group['close'] >= ma20_series).values
        slow_climb = 0
        for val in reversed(above_ma20):
            if val:
                slow_climb += 1
            else:
                break

        tech_results[t] = {
            'latest_close': latest_close,
            'latest_date': latest_date,
            'return_6m': ret_6m,
            'return_1y': ret_1y,
            'return_2y': ret_2y,
            'return_3y': ret_3y,
            'high_52w': high_52w,
            'dist_to_52w_high': dist_52w,
            'max_drawdown_1y': max_dd_1y,
            'volatility_1y': vol_1y,
            'slow_climb_days': slow_climb
        }

    print(f"✓ 技术指标计算完成，共覆盖 {len(tech_results)} 只美股")
    return tech_results


def step5_fetch_yfinance_fundamentals(tickers):
    print("\n" + "=" * 60)
    print("Step 5: 获取 yfinance 基本面估值 (严格执行 D8 绝不抓卖方一致预期)")
    print("=" * 60)

    cached_data = {}
    if os.path.exists(YF_CACHE_PATH):
        try:
            with open(YF_CACHE_PATH, "r") as f:
                raw_cache = json.load(f)
            # 仅保留真正拿到 marketCap 的有效条目
            cached_data = {k: v for k, v in raw_cache.items() if v.get('marketCap') is not None}
            print(f"  已载入有效缓存 {len(cached_data)} 条")
        except Exception:
            cached_data = {}

    to_fetch = [t for t in tickers if t not in cached_data]
    print(f"  待抓取/补全标的数: {len(to_fetch)} (已有有效缓存: {len(cached_data)})")

    def fetch_single(t):
        try:
            tk = yf.Ticker(t)
            info = tk.info or {}
            # 严格按照指定字段提取，绝不碰 forwardPE, targetMeanPrice, recommendationKey (规则 D8)
            mc = info.get('marketCap')
            if mc is None:
                # 尝试 fast_info 作为兜底
                try:
                    mc = tk.fast_info.get('market_cap')
                except Exception:
                    pass
            res = {
                'ticker': t,
                'marketCap': mc,
                'trailingPE': info.get('trailingPE'),
                'priceToSalesTrailing12Months': info.get('priceToSalesTrailing12Months'),
                'returnOnEquity': info.get('returnOnEquity'),
                'grossMargins': info.get('grossMargins'),
                'operatingMargins': info.get('operatingMargins'),
                'revenueGrowth': info.get('revenueGrowth'),
                'earningsGrowth': info.get('earningsGrowth'),
                'enterpriseValue': info.get('enterpriseValue'),
                'totalCash': info.get('totalCash'),
                'totalDebt': info.get('totalDebt'),
                'sector': info.get('sector'),
                'industry': info.get('industry'),
                'country': info.get('country')
            }
            return t, res, None
        except Exception as e:
            return t, None, str(e)

    if to_fetch:
        # 使用 max_workers=3 + 适度平滑，避免 429
        t0 = time.time()
        completed = 0
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_ticker = {executor.submit(fetch_single, t): t for t in to_fetch}
            for future in as_completed(future_to_ticker):
                t, res, err = future.result()
                if res and res.get('marketCap') is not None:
                    cached_data[t] = res
                else:
                    print(f"    [WARN] {t} 抓取受限或无返回: {err}")
                    if res:
                        cached_data[t] = res
                completed += 1
                if completed % 10 == 0 or completed == len(to_fetch):
                    elapsed = time.time() - t0
                    print(f"    进度: {completed}/{len(to_fetch)} ({completed/len(to_fetch)*100:.1f}%), 耗时: {elapsed:.1f}s")

        # 写缓存
        with open(YF_CACHE_PATH, "w") as f:
            json.dump(cached_data, f)
        print(f"✓ yfinance 抓取完毕并写回缓存: {YF_CACHE_PATH}")

    return cached_data


def step6_merge_and_save(tickers, feishu_dict, jumps_dict, tech_dict, yf_dict, df_uni):
    print("\n" + "=" * 60)
    print("Step 6: 合并全量特征并输出 Parquet")
    print("=" * 60)

    uni_map = df_uni.set_index('ticker').to_dict('index')

    rows = []
    for t in tickers:
        uni_info = uni_map.get(t, {})
        yf_info = yf_dict.get(t, {})
        tech_info = tech_dict.get(t, {})
        jump_info = jumps_dict.get(t, {})
        feishu_info = feishu_dict.get(t, {})

        # 市值确定 (优先 yfinance 真实最新 marketCap，兜底 universe)
        mc_yf = yf_info.get('marketCap')
        mc_uni = uni_info.get('market_cap')
        market_cap_final = mc_yf if mc_yf is not None else mc_uni
        market_cap_b = market_cap_final / 1e9 if market_cap_final is not None else None

        # 重点标注标志位
        is_ge_25b = bool(market_cap_final is not None and market_cap_final >= 25e9)
        is_ge_20b = bool(market_cap_final is not None and market_cap_final >= 20e9)
        is_ge_15b = bool(market_cap_final is not None and market_cap_final >= 15e9)
        in_feishu_q3 = bool(t in feishu_dict)

        row = {
            'ticker': t,
            'name': uni_info.get('name') or yf_info.get('shortName'),
            'sector': yf_info.get('sector') or uni_info.get('sector'),
            'industry': yf_info.get('industry') or uni_info.get('industry'),
            'country': yf_info.get('country', 'United States'),
            'market_cap': market_cap_final,
            'market_cap_usd_b': market_cap_b,
            'is_large_cap_25b': is_ge_25b,
            'is_mid_large_20b': is_ge_20b,
            'is_ge_15b': is_ge_15b,
            'is_non_china': True,

            # 飞书 2026Q3 专区信息
            'in_feishu_q3': in_feishu_q3,
            'feishu_q3_beat_miss': feishu_info.get('beat_miss'),
            'feishu_q3_report_date': feishu_info.get('report_date'),
            'feishu_q3_reaction_desc': feishu_info.get('price_reaction_desc'),
            'feishu_q3_title': feishu_info.get('title'),
            'feishu_q3_node_token': feishu_info.get('node_token'),
            'feishu_q3_url': feishu_info.get('url'),

            # 财报跳涨记录 (来自 1_选股_美股2026中报财报日涨跌.xlsx)
            'has_jump_26q3': jump_info.get('has_jump_26q3', False),
            'jump_date_26q3': jump_info.get('jump_date_26q3'),
            'jump_pct_26q3': jump_info.get('jump_pct_26q3'),
            'jump_timing_26q3': jump_info.get('jump_timing_26q3'),
            'jump_return_since_26q3': jump_info.get('jump_return_since_26q3'),
            'has_jump_26q2': jump_info.get('has_jump_26q2', False),
            'jump_date_26q2': jump_info.get('jump_date_26q2'),
            'jump_pct_26q2': jump_info.get('jump_pct_26q2'),
            'jump_timing_26q2': jump_info.get('jump_timing_26q2'),
            'jump_return_since_26q2': jump_info.get('jump_return_since_26q2'),
            'jump_sector_tag': jump_info.get('jump_sector_tag'),
            'jump_outcome': jump_info.get('jump_outcome'),

            # 日频技术指标 (截至 2026-11-06)
            'latest_close': tech_info.get('latest_close'),
            'latest_date': tech_info.get('latest_date'),
            'return_6m': tech_info.get('return_6m'),
            'return_1y': tech_info.get('return_1y'),
            'return_2y': tech_info.get('return_2y'),
            'return_3y': tech_info.get('return_3y'),
            'high_52w': tech_info.get('high_52w'),
            'dist_to_52w_high': tech_info.get('dist_to_52w_high'),
            'max_drawdown_1y': tech_info.get('max_drawdown_1y'),
            'volatility_1y': tech_info.get('volatility_1y'),
            'slow_climb_days': tech_info.get('slow_climb_days'),

            # 基本面真实估值指标 (严格按 D8 规则，无卖方一致预期)
            'trailingPE': yf_info.get('trailingPE'),
            'priceToSalesTrailing12Months': yf_info.get('priceToSalesTrailing12Months'),
            'returnOnEquity': yf_info.get('returnOnEquity'),
            'grossMargins': yf_info.get('grossMargins'),
            'operatingMargins': yf_info.get('operatingMargins'),
            'revenueGrowth': yf_info.get('revenueGrowth'),
            'earningsGrowth': yf_info.get('earningsGrowth'),
            'enterpriseValue': yf_info.get('enterpriseValue'),
            'totalCash': yf_info.get('totalCash'),
            'totalDebt': yf_info.get('totalDebt'),
        }
        rows.append(row)

    df_final = pd.DataFrame(rows)
    df_final.to_parquet(CANDIDATES_PARQUET_PATH, index=False)
    print(f"✓ 全量候选特征表已保存至: {CANDIDATES_PARQUET_PATH}")
    print(f"  总行数: {len(df_final)}")
    print(f"  >$25B 非中概美股总数 (is_large_cap_25b=True): {df_final['is_large_cap_25b'].sum()}")
    print(f"  >$20B 非中概美股总数 (is_mid_large_20b=True): {df_final['is_mid_large_20b'].sum()}")
    print(f"  飞书 Q3 美股专区命中数 (in_feishu_q3=True): {df_final['in_feishu_q3'].sum()} (全部 73 只 100% 命中)")
    print(f"  26Q3 财报跳涨命中数 (has_jump_26q3=True): {df_final['has_jump_26q3'].sum()}")
    print(f"  26Q2 财报跳涨命中数 (has_jump_26q2=True): {df_final['has_jump_26q2'].sum()}")

    return df_final


def main():
    print("=" * 70)
    print("启动 W1_11: 2026Q3 飞书172篇财报库与美股 >$25B 选股底座提取器")
    print("=" * 70)

    # 1. 飞书 172 篇
    feishu_inv = step1_fetch_feishu_inventory()

    # 2. 活表跳涨记录
    jumps = step2_load_jumps()

    # 3. 候选宇宙构建
    tickers, feishu_dict, df_uni = step3_prepare_universe(feishu_inv)

    # 4. 日频技术指标
    tech_dict = step4_compute_price_technicals(tickers)

    # 5. yfinance 基本面估值 (无卖方一致预期)
    yf_dict = step5_fetch_yfinance_fundamentals(tickers)

    # 6. 合并保存
    df_res = step6_merge_and_save(tickers, feishu_dict, jumps, tech_dict, yf_dict, df_uni)

    print("\n" + "=" * 70)
    print("W1_11 执行完毕！")
    print("=" * 70)


if __name__ == "__main__":
    main()
