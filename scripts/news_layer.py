#!/usr/bin/env python3
"""
news_layer.py — A股交易session消息面数据层
参考 news-dashboard 机制(signal_intelligence 6维评分简化版 + 多源快讯抓取)。

三块产出:
  ① overnight_us : 隔夜美股(费半SOX/纳指/道指涨跌 + 下跌原因头条)
  ② cn_flash     : 今日A股快讯(财联社电报/新浪7x24/华尔街见闻/东财7x24, 最近12小时)
  ③ policy       : 重大政策头条(中国政府网政策文件库 + 发改委兜底)

评分: 参考 signal_config 关键词分级 critical/high/medium/low →
      base 95/80/60/40, 命中持仓 +15 / 命中watchlist +8, cap 100。
持仓/watchlist 来自 portfolio_state.json + watchlist_config.json 动态读取(不硬编码)。

输出: data/news_today.json + CLI摘要。
单源失败 skip 不崩。全部请求 timeout=8。
"""
import os
os.environ['NO_PROXY'] = '*'   # ⛔必须在import requests前: 绕代理DNS劫持(见reference_eastmoney_proxy_fix)

import hashlib
import html
import json
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

# ---------------------------------------------------------------- 常量
BASE = os.path.expanduser('~/claude-projects/sim-portfolio')
STATE_FILE = os.path.join(BASE, 'portfolio_state.json')
WATCHLIST_FILE = os.path.join(BASE, 'watchlist_config.json')
OUT_FILE = os.path.join(BASE, 'data', 'news_today.json')

UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
T = 8  # 全局timeout(秒)
CST = timezone(timedelta(hours=8))
NOW = datetime.now(CST)
CUTOFF_12H = NOW - timedelta(hours=12)

# 关键词分级(signal_config magnitude表 A股化, 参考news-dashboard signal_intelligence)
KW_CRITICAL = [
    '降息', '加息', '降准', '国常会', '政治局', '中央经济工作会议', '印花税',
    '关税', '制裁', '实体清单', '出口管制', '反倾销', '稀土管制',
    '立案', '退市', '破产', '涨停潮', '熔断', '战争', '停战', '国九条',
]
KW_HIGH = [
    '涨停', '跌停', '中标', '减持', '增持', '回购', '收购', '重组', '停牌',
    '扩产', '涨价', '提价', '业绩预告', '预增', '预亏', '商誉减值',
    '大基金', '国产替代', '专项债', '特别国债',
    '发改委', '国家发展改革委', '工信部', '工业和信息化部', '央行', '中国人民银行',
    '证监会', '国务院', '能源体系', '设备更新',
    '英伟达', 'Nvidia', 'AI', 'OpenAI', '算力', '半导体', '芯片', '光模块',
]
KW_MEDIUM = [
    '财报', '季报', '指引', 'guidance', '评级', '目标价', '融资', '定增',
    'IPO', '解禁', '主力资金', '北向', '板块异动', '开盘', '拉升', '走强', '大涨',
]

# ---------------------------------------------------------------- 持仓/watchlist加载

def load_universe():
    """从SSOT动态读持仓与watchlist名单: {name_or_ticker: ('position'|'watchlist', display)}"""
    uni = {}
    try:
        state = json.load(open(STATE_FILE))
        for mkt in ('a_share', 'us'):
            for p in state['accounts'][mkt].get('positions', []) or []:
                tk, nm = str(p.get('ticker', '')), str(p.get('name', ''))
                for key in (tk, nm):
                    if key and len(key) >= 2:
                        uni[key] = ('position', f'{nm}({tk})')
    except Exception as e:
        print(f'[warn] portfolio_state读取失败: {e}', file=sys.stderr)
    try:
        wl = json.load(open(WATCHLIST_FILE))
        for lst in ('cn_watchlist', 'us_watchlist', 'us_watchlist_new'):
            for w in wl.get(lst, []) or []:
                tk, nm = str(w.get('ticker', '')), str(w.get('name', ''))
                for key in (tk, nm):
                    if key and len(key) >= 2 and key not in uni:
                        uni[key] = ('watchlist', f'{nm}({tk})')
    except Exception as e:
        print(f'[warn] watchlist_config读取失败: {e}', file=sys.stderr)
    return uni

UNIVERSE = load_universe()

# ---------------------------------------------------------------- 评分

def match_related(text):
    """返回 (related_tickers列表, 是否命中持仓, 是否命中watchlist)"""
    hits, pos_hit, wl_hit = [], False, False
    for key, (kind, disp) in UNIVERSE.items():
        # 纯数字ticker只在含代码语境匹配(避免'300308'撞时间戳): 直接子串即可, A股代码6位少误撞
        if key in text:
            if disp not in hits:
                hits.append(disp)
            if kind == 'position':
                pos_hit = True
            else:
                wl_hit = True
    return hits, pos_hit, wl_hit


def score_item(text, extra_stock_field=''):
    """关键词分级 + portfolio_relevance → 0-100分"""
    base = 40
    for kw in KW_CRITICAL:
        if kw in text:
            base = 95
            break
    if base < 95:
        for kw in KW_HIGH:
            # ⚠️纯ASCII词(AI/Nvidia)必须加词边界: 'ai' in 'said/daily/chain'.lower()会把任意英文标题误抬到80
            if kw.isascii():
                if re.search(r'(?<![A-Za-z0-9])' + re.escape(kw) + r'(?![A-Za-z0-9])', text, re.I):
                    base = 80
                    break
            elif kw in text:
                base = 80
                break
    if base < 80:
        for kw in KW_MEDIUM:
            if kw in text:
                base = 60
                break
    related, pos_hit, wl_hit = match_related(text + ' ' + str(extra_stock_field))
    if pos_hit:
        base = min(100, base + 15)
    elif wl_hit:
        base = min(100, base + 8)
    return base, related

# ---------------------------------------------------------------- 去重(news-dashboard server.py同款: 归一化标题重叠率)

def _norm(t):
    return re.sub(r'[^0-9A-Za-z一-鿿]', '', t).lower()


def dedupe(items):
    seen, out = [], []
    for it in items:
        n = _norm(it['title'])
        if not n:
            continue
        dup = False
        for s in seen:
            shorter, longer = (n, s) if len(n) <= len(s) else (s, n)
            if len(shorter) and sum(1 for c in set(shorter) if c in longer) / len(set(shorter)) > 0.8 \
               and abs(len(n) - len(s)) < max(len(n), len(s)) * 0.5:
                dup = True
                break
        if not dup:
            seen.append(n)
            out.append(it)
    return out

# ---------------------------------------------------------------- ① 隔夜美股

def yahoo_index(symbol):
    """隔夜变动 = 最近两根日线close之比。
    ⛔不可用meta['chartPreviousClose'](=range窗口前收盘,算出来是多日累计,方向都可能错:
    07-02实测IXIC给+0.85%而真实隔夜-0.66%); meta里regularMarketPreviousClose为None不可依赖。"""
    r = requests.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}',
                     params={'range': '5d', 'interval': '1d'}, headers=UA, timeout=T)
    res = r.json()['chart']['result'][0]
    px = res['meta']['regularMarketPrice']
    closes = [c for c in res['indicators']['quote'][0]['close'] if c is not None]
    if len(closes) >= 2 and abs(closes[-1] - px) / px < 0.001:
        pc = closes[-2]          # 最后一根bar=当前价(收盘后) → 前收=倒数第二根
    elif closes:
        pc = closes[-1]          # 盘中: 最后一根完整bar即前收
    else:
        pc = res['meta']['chartPreviousClose']
    return round(px, 2), round((px / pc - 1) * 100, 2)


def yahoo_rss_titles(symbol='^IXIC', n=6):
    r = requests.get('https://feeds.finance.yahoo.com/rss/2.0/headline',
                     params={'s': symbol, 'region': 'US', 'lang': 'en-US'}, headers=UA, timeout=T)
    titles = re.findall(r'<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', r.text)[1:]
    return [html.unescape(t.strip()) for t in titles if t.strip()][:n]


def fetch_overnight_us():
    out = {'sox': None, 'sox_chg': None, 'ndx': None, 'ndx_chg': None,
           'dji': None, 'dji_chg': None, 'top_reasons': [], 'sources_ok': []}
    for key, sym in (('sox', '^SOX'), ('ndx', '^IXIC'), ('dji', '^DJI')):
        try:
            px, chg = yahoo_index(sym)
            out[key], out[key + '_chg'] = px, chg
            out['sources_ok'].append(f'yahoo:{sym}')
        except Exception as e:
            print(f'[skip] yahoo {sym}: {e}', file=sys.stderr)
    # 东财中文指数兜底(无SOX代码, 只补NDX/DJIA)
    if out['ndx_chg'] is None or out['dji_chg'] is None:
        try:
            r = requests.get('https://push2.eastmoney.com/api/qt/ulist.np/get',
                             params={'secids': '100.NDX,100.DJIA,100.SPX',
                                     'fields': 'f2,f3,f4,f12,f14', 'fltt': 2},
                             headers=UA, timeout=T)
            for d in r.json()['data']['diff']:
                if d['f12'] == 'NDX' and out['ndx_chg'] is None:
                    out['ndx'], out['ndx_chg'] = d['f2'], d['f3']
                if d['f12'] == 'DJIA' and out['dji_chg'] is None:
                    out['dji'], out['dji_chg'] = d['f2'], d['f3']
            out['sources_ok'].append('eastmoney:ulist')
        except Exception as e:
            print(f'[skip] em_us_index: {e}', file=sys.stderr)
    # 头条原因: ^SOX优先(费半=A股半导体链最相关驱动, 07-02实测Meta卖算力线索只在SOX feed里) + ^IXIC补充
    reasons = []
    for sym in ('^SOX', '^IXIC'):
        try:
            for t in yahoo_rss_titles(sym):
                if t not in reasons:
                    reasons.append(t)
            out['sources_ok'].append(f'yahoo:rss:{sym}')
        except Exception as e:
            print(f'[skip] yahoo rss {sym}: {e}', file=sys.stderr)
    out['top_reasons'] = reasons[:8]
    return out

# ---------------------------------------------------------------- ② A股快讯(四路冗余)

def cls_telegraph(rn=30):
    """财联社电报。⚠️旧nodeapi/telegraphList已404, 用v1/roll + md5(sha1(排序参数串))签名"""
    params = {'app': 'CailianpressWeb', 'category': '', 'last_time': '',
              'os': 'web', 'refresh_type': '1', 'rn': str(rn), 'sv': '8.4.6'}
    qs = '&'.join(f'{k}={v}' for k, v in sorted(params.items()))
    params['sign'] = hashlib.md5(hashlib.sha1(qs.encode()).hexdigest().encode()).hexdigest()
    r = requests.get('https://www.cls.cn/v1/roll/get_roll_list', params=params,
                     headers={**UA, 'Referer': 'https://www.cls.cn/telegraph'}, timeout=T)
    out = []
    for d in r.json()['data']['roll_data']:
        ts = datetime.fromtimestamp(int(d.get('ctime', 0)), CST)
        stocks = d.get('stocks_extends') or d.get('author_extends') or ''
        title = (d.get('title') or '').strip() or (d.get('brief') or '').strip() \
                or (d.get('content') or '').strip()[:80]
        out.append({'time': ts, 'title': title, 'text': d.get('content', ''),
                    'stocks': str(stocks), 'src': 'cls'})
    return out


def sina_7x24(n=30):
    r = requests.get('https://zhibo.sina.com.cn/api/zhibo/feed',
                     params={'page': 1, 'page_size': n, 'zhibo_id': 152}, headers=UA, timeout=T)
    out = []
    for d in r.json()['result']['data']['feed']['list']:
        ts = datetime.strptime(d['create_time'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=CST)
        txt = re.sub(r'<[^>]+>', '', d.get('rich_text', '')).strip()
        out.append({'time': ts, 'title': txt[:80], 'text': txt,
                    'stocks': str(d.get('ext', '')), 'src': 'sina'})
    return out


def wscn_lives(n=30):
    r = requests.get('https://api-one.wallstcn.com/apiv1/content/lives',
                     params={'channel': 'global-channel', 'client': 'pc', 'limit': n}, timeout=T)
    out = []
    for d in r.json()['data']['items']:
        ts = datetime.fromtimestamp(int(d['display_time']), CST)
        txt = re.sub(r'<[^>]+>', '', d.get('content_text', '')).strip()
        title = (d.get('title') or '').strip() or txt[:80]
        score_flag = d.get('score')  # score=2为重要
        out.append({'time': ts, 'title': title, 'text': txt,
                    'stocks': '', 'src': 'wscn', 'important': score_flag == 2})
    return out


def em_7x24(n=30):
    r = requests.get('https://np-listapi.eastmoney.com/comm/web/getFastNewsList',
                     params={'client': 'web', 'biz': 'web_724', 'fastColumn': '102',
                             'sortEnd': '', 'pageSize': n, 'req_trace': '1'},
                     headers=UA, timeout=T)
    out = []
    for d in r.json()['data']['fastNewsList']:
        ts = datetime.strptime(d['showTime'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=CST)
        out.append({'time': ts, 'title': (d.get('title') or '').strip() or d.get('summary', '')[:80],
                    'text': d.get('summary', ''), 'stocks': str(d.get('stockList', [])), 'src': 'em'})
    return out


def fetch_cn_flash():
    raw, sources_ok = [], []
    for fn in (cls_telegraph, sina_7x24, wscn_lives, em_7x24):
        try:
            items = fn()
            raw.extend(items)
            sources_ok.append(fn.__name__)
        except Exception as e:
            print(f'[skip] {fn.__name__}: {e}', file=sys.stderr)
    # 12小时窗口
    raw = [it for it in raw if it['time'] >= CUTOFF_12H]
    raw.sort(key=lambda x: x['time'], reverse=True)
    raw = dedupe(raw)
    flash = []
    for it in raw:
        sc, related = score_item(it['title'] + ' ' + it['text'], it.get('stocks', ''))
        if it.get('important'):
            sc = min(100, sc + 5)  # 华尔街见闻score=2标记
        flash.append({'time': it['time'].strftime('%Y-%m-%d %H:%M'),
                      'title': it['title'], 'score': sc,
                      'related_tickers': related, 'src': it['src']})
    flash.sort(key=lambda x: (-x['score'], x['time']), reverse=False)
    return flash, sources_ok

# ---------------------------------------------------------------- ③ 重大政策

def gov_policy(n=10):
    """中国政府网政策文件库(部门文件: 发改委/工信部/央行等), 按发布时间"""
    r = requests.get('https://sousuo.www.gov.cn/search-gov/data',
                     params={'t': 'zhengcelibrary_bm', 'q': '', 'timetype': 'timeqb',
                             'mintime': '', 'maxtime': '', 'sort': 'pubtime', 'sortType': '1',
                             'searchfield': 'title', 'pcodeJiguan': '', 'childtype': '',
                             'subchildtype': '', 'puborg': '', 'pcodeYear': '', 'pcodeNum': '',
                             'filetype': '', 'p': '1', 'n': str(n), 'inpro': '',
                             'bmfl': '', 'dup': '', 'orpro': ''},
                     headers=UA, timeout=T)
    out = []
    for d in r.json()['searchVO']['listVO']:
        title = re.sub(r'<[^>]+>', '', d.get('title', '')).strip()
        out.append({'title': title, 'org': d.get('puborg', ''),
                    'pub_date': d.get('pubtimeStr', ''), 'url': d.get('url', ''), 'src': 'gov.cn'})
    return out


def ndrc_policy(n=10):
    """发改委政策列表HTML兜底"""
    r = requests.get('https://www.ndrc.gov.cn/xxgk/zcfb/tz/index.html', headers=UA, timeout=T)
    r.encoding = 'utf-8'
    items = re.findall(r'<li[^>]*>\s*<a[^>]*title="([^"]+)"', r.text)[:n]
    return [{'title': t.strip(), 'org': '国家发展改革委', 'pub_date': '', 'url': '', 'src': 'ndrc'}
            for t in items]


def fetch_policy():
    items, sources_ok = [], []
    try:
        items = gov_policy()
        sources_ok.append('gov_policy')
    except Exception as e:
        print(f'[skip] gov_policy: {e}', file=sys.stderr)
    if not items:
        try:
            items = ndrc_policy()
            sources_ok.append('ndrc_policy')
        except Exception as e:
            print(f'[skip] ndrc_policy: {e}', file=sys.stderr)
    out = []
    for it in items:
        sc, related = score_item(it['title'])
        out.append({**it, 'score': sc, 'related_tickers': related})
    out.sort(key=lambda x: -x['score'])
    return out, sources_ok

# ---------------------------------------------------------------- 主流程

def main():
    print(f'=== news_layer 消息面数据层 {NOW.strftime("%Y-%m-%d %H:%M")} CST ===')
    print(f'持仓/watchlist名单: {len(UNIVERSE)}个匹配键(动态读自portfolio_state+watchlist_config)\n')

    overnight = fetch_overnight_us()
    cn_flash, flash_src = fetch_cn_flash()
    policy, policy_src = fetch_policy()

    result = {
        'fetched_at': NOW.isoformat(),
        'overnight_us': overnight,
        'cn_flash': cn_flash,
        'policy': policy,
        '_meta': {
            'sources_ok': overnight.get('sources_ok', []) + flash_src + policy_src,
            'flash_window_hours': 12,
            'scoring': 'keyword tier critical=95/high=80/medium=60/low=40; +15持仓命中/+8watchlist命中',
        },
    }
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, 'w') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # ---- CLI摘要 ----
    print('【隔夜美股】')
    for key, label in (('sox', '费半SOX'), ('ndx', '纳指'), ('dji', '道指')):
        if result['overnight_us'].get(key) is not None:
            chg = result['overnight_us'][key + '_chg']
            print(f'  {label}: {result["overnight_us"][key]}  {chg:+.2f}%')
    for t in overnight['top_reasons'][:4]:
        print(f'  · {t}')

    print(f'\n【A股快讯 最近12h】共{len(cn_flash)}条(去重后), 来源: {", ".join(flash_src) or "无"}')
    for it in cn_flash[:12]:
        rel = ' ⭐' + '/'.join(it['related_tickers'][:3]) if it['related_tickers'] else ''
        print(f'  [{it["score"]:>3}] {it["time"][11:]} ({it["src"]}) {it["title"][:56]}{rel}')

    print(f'\n【重大政策】共{len(policy)}条, 来源: {", ".join(policy_src) or "无"}')
    for it in policy[:6]:
        print(f'  [{it["score"]:>3}] {it["pub_date"][:10]:>10} {it["org"][:12]} | {it["title"][:50]}')

    hi = [x for x in cn_flash if x['score'] >= 80]
    port = [x for x in cn_flash if x['related_tickers']]
    print(f'\n汇总: 高分快讯(≥80) {len(hi)}条 | 持仓/watchlist相关 {len(port)}条')
    print(f'已写入: {OUT_FILE}')


if __name__ == '__main__':
    main()
