#!/usr/bin/env python3
"""
news_layer.py — A股交易session消息面数据层
参考 news-dashboard 机制(signal_intelligence 6维评分简化版 + 多源快讯抓取)。

四块产出:
  ① overnight_us : 隔夜美股(费半SOX/纳指/道指涨跌 + 下跌原因头条)
  ② cn_flash     : 今日A股快讯(财联社电报/新浪7x24/华尔街见闻/东财7x24, 最近12小时)
  ③ policy       : 重大政策头条(中国政府网政策文件库 + 发改委兜底)
  ④ discovery    : ⛔2026-08-14新增·新标的发现层(B6前瞻信号层)。旧版match_related()只能给
                    "已在持仓/watchlist"的标的加分,产业级新闻(光纤涨价/MLCC交期/钨价)命中的是
                    行业关键词而非具体ticker,结构上永远升不到候选——这是"中芯国际信号进来了但
                    停在待深扫"同一根病灶的另一半。discovery反查 data/product_tree_map.json(36棵
                    树/859只),把关键词命中的产业树上"未在watchlist里"的成分股一并提出来当新候选,
                    而不是只在已覆盖名单里打转。见 §discovery。

评分: 参考 signal_config 关键词分级 critical/high/medium/low →
      base 95/80/60/40, 命中持仓 +15 / 命中watchlist +8, cap 100。
持仓/watchlist 来自 portfolio_state.json + watchlist_config.json 动态读取(不硬编码)。

输出: data/news_today.json(含新增discovery字段) + CLI摘要。
单源失败 skip 不崩。全部请求 timeout=8。
"""
import os
os.environ['NO_PROXY'] = '*'   # ⛔必须在import requests前: 绕代理DNS劫持(见reference_eastmoney_proxy_fix)
os.environ.setdefault('no_proxy', '*')

import hashlib
import html
import json
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tree_anomaly_scan as tas  # noqa: E402  (复用load_tree_map,不重造解析逻辑;import即装yfinance拦截器)

# ---------------------------------------------------------------- 常量
BASE = os.path.expanduser('~/claude-projects/sim-portfolio')
STATE_FILE = os.path.join(BASE, 'portfolio_state.json')
WATCHLIST_FILE = os.path.join(BASE, 'watchlist_config.json')
TREE_MAP_FILE = os.path.join(BASE, 'data', 'product_tree_map.json')
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

# ---------------------------------------------------------------- §discovery 新标的发现(2026-08-14 B6新增)

# 产业关键词→产品树反查用的触发词典。⚠️2026-08-14实跑修正两轮:
#  轮1: 最初版本把"新闻里出现的词"和"树/节点名称里的词"合成一个list直接互相子串匹配,结果当天
#       "A股PCB概念股震荡拉升"这条真实新闻(华正新材涨停/南亚新材涨超6%,两者都在"玻纤布/CCL覆铜板"
#       节点上且都不在watchlist)因为新闻讲"PCB"而节点名讲"CCL覆铜板",两个词互不为子串,直接漏判——
#       证明"新闻词汇"和"产业树词汇"不是同一套字典,必须显式建立映射,不能指望字面重合。
#  轮2: 轮1修完后用真实"稀土板块走强"快讯实跑,发现match_substrs对着"tree名+node名"一起匹配时,
#       "树1: 电动车(...)——...最上游=锂矿/稀土矿/萤石矿"这种树名本身是"全链条摘要式命名"，
#       名字里捎带提了"稀土矿"/"萤石矿",导致"稀土"关键词把整条电动车链(整车/电池/电机/电解液/
#       负极/正极/隔膜...47个跟稀土毫无关系的成分股)全部错判成候选——树名是"全链摘要",不是
#       "这个entry实际在哪个环节"的准确定位,只有node字段才是。⛔改为只匹配node,不看tree名。
#       (代价: 部分子串如"成熟制程涨价"原本靠命中树名才work,node里只写"成熟制程"不含"涨价"二字,
#       已同步把子串改成实际出现在node文本里的短语,逐一核对过, 见下方注释标注)
# 结构: 触发词(可能出现在新闻原文里) → node名称里等价的匹配子串列表(命中任一即算这个node相关)。
INDUSTRY_KEYWORD_MAP = {
    '光纤': ['光纤'], '光棒': ['光棒'], '芯公里': ['光纤'], '光缆': ['光缆'],
    'MLCC': ['MLCC'], '陶瓷电容': ['陶瓷电容'],
    '被动元件': ['被动元件', '电容'], '电容器涨价': ['MLCC', '电容'],
    'PCB': ['玻纤布', 'CCL覆铜板'], '覆铜板': ['玻纤布', 'CCL覆铜板'],
    '电子布': ['玻纤布', 'CCL覆铜板'], '玻纤': ['玻纤布', 'CCL覆铜板'],
    'CCL': ['玻纤布', 'CCL覆铜板'], '玻璃纤维': ['玻纤布', 'CCL覆铜板'],
    '钨精矿': ['钨矿', 'APT'], 'APT': ['APT'],
    '仲钨酸铵': ['APT', '仲钨酸铵'], '硬质合金': ['硬质合金'],
    '制冷剂': ['制冷剂'], '氟化工': ['氟化工'], 'HFCs': ['制冷剂'],
    'R32': ['制冷剂'], 'R125': ['制冷剂'], 'R134a': ['制冷剂'], '萤石': ['萤石矿'],
    '稀土': ['稀土'], '稀土配额': ['稀土'], '稀土出口管制': ['稀土'], '稀土总量控制': ['稀土'],
    # ⚠️node文本只写"成熟制程"(如"代工厂-成熟制程龙头"),不含"涨价"二字,子串必须照抄node原文。
    # 'IDM'补进来是因为士兰微/华润微这类IDM厂商node写的是"IDM-功率半导体"不含"成熟制程"字面,
    # 但确属这条涨价链——'IDM'子串经查验只出现在树4内部(见INDUSTRY_KEYWORD_MAP轮2注释旁的
    # 实测: grep全map, 'IDM'仅命中树4三个node), 不会重犯"稀土矿"那种跨树误伤。
    '晶圆代工': ['成熟制程', '代工厂', 'IDM'], '代工ASP': ['成熟制程', '代工厂', 'IDM'],
    '成熟制程': ['成熟制程'], '代工涨价': ['成熟制程', '代工厂', 'IDM'],
    'DRAM': ['DRAM', '存储'], 'NAND': ['NAND', '存储'], '存储芯片': ['存储'],
    '存储涨价': ['存储'], '内存条': ['存储'],
}
INDUSTRY_KEYWORDS = list(INDUSTRY_KEYWORD_MAP.keys())

TREE_ENTRIES = tas.load_tree_map(TREE_MAP_FILE) or []
if not TREE_ENTRIES:
    print(f'[warn] 产品树映射为空或不存在: {TREE_MAP_FILE}, discovery层将始终返回空', file=sys.stderr)


def discover_new_candidates(text):
    """产业关键词命中 → 反查product_tree_map里对应的树/节点 → 挑出'未在watchlist/持仓里'的成分股。
    这是旧match_related()的镜像函数: match_related只能给"已在名单里"的标的加分(结构性只认已知票),
    discover_new_candidates专门找"名单外"的票,解决"产业级新闻升不到具体标的候选"的问题。
    ⛔只匹配node文本(不含tree名): tree名常是"全链条摘要式命名"会捎带提到不相关材料,node才是
    准确的环节定位,见上方INDUSTRY_KEYWORD_MAP注释轮2的真实事故。
    返回: [{'ticker','name','tree','node','matched_keyword'}, ...] 已按(ticker,tree)去重。"""
    hit_kws = [kw for kw in INDUSTRY_KEYWORDS if kw in text]
    if not hit_kws or not TREE_ENTRIES:
        return []
    match_substrs = {s for kw in hit_kws for s in INDUSTRY_KEYWORD_MAP[kw]}
    out, seen = [], set()
    for e in TREE_ENTRIES:
        haystack = e.get('node') or ''
        hit_sub = next((s for s in match_substrs if s in haystack), None)
        if not hit_sub:
            continue
        code, name = e['ticker'], e.get('name') or ''
        if code in UNIVERSE or name in UNIVERSE:
            continue  # 已在持仓/watchlist名单里, 不算"新发现"(discovery只管名单外)
        key = (code, e.get('tree'))
        if key in seen:
            continue
        seen.add(key)
        # matched_keyword报"新闻原文里实际出现的词"(便于人工回溯为什么命中),不是树名子串
        matched_kw = next((kw for kw in hit_kws if hit_sub in INDUSTRY_KEYWORD_MAP[kw]), hit_sub)
        out.append({'ticker': code, 'name': name, 'tree': e.get('tree'),
                    'node': e.get('node'), 'matched_keyword': matched_kw})
    return out

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
        full_text = it['title'] + ' ' + it['text']
        sc, related = score_item(full_text, it.get('stocks', ''))
        if it.get('important'):
            sc = min(100, sc + 5)  # 华尔街见闻score=2标记
        new_cands = discover_new_candidates(full_text)
        row = {'time': it['time'].strftime('%Y-%m-%d %H:%M'),
               'title': it['title'], 'score': sc,
               'related_tickers': related, 'src': it['src']}
        if new_cands:
            row['new_candidates'] = new_cands
        flash.append(row)
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
        row = {**it, 'score': sc, 'related_tickers': related}
        new_cands = discover_new_candidates(it['title'])
        if new_cands:
            row['new_candidates'] = new_cands
        out.append(row)
    out.sort(key=lambda x: -x['score'])
    return out, sources_ok


def build_discovery_digest(cn_flash, policy):
    """聚合cn_flash+policy里的new_candidates → 去重后的今日新发现候选清单(discovery顶层字段)。
    每个候选票带首次触发它的新闻标题+分数+关键词, 供SLA闭环脚本(signal_sla_check.py)消费:
    ⛔命中discovery≠自动进池, 只是把"名单外但产业树上有名"的票从噪音里捞出来, 终态裁决仍由人工/agent做。"""
    seen: dict[str, dict] = {}
    for source_kind, items in (('cn_flash', cn_flash), ('policy', policy)):
        for it in items:
            for c in it.get('new_candidates', []):
                key = c['ticker']
                if key not in seen:
                    seen[key] = {**c, 'first_seen_title': it.get('title'),
                                 'first_seen_score': it.get('score'),
                                 'first_seen_src': it.get('src') or source_kind}
    return sorted(seen.values(), key=lambda x: -(x.get('first_seen_score') or 0))

# ---------------------------------------------------------------- 主流程

def main():
    print(f'=== news_layer 消息面数据层 {NOW.strftime("%Y-%m-%d %H:%M")} CST ===')
    print(f'持仓/watchlist名单: {len(UNIVERSE)}个匹配键(动态读自portfolio_state+watchlist_config)\n')

    overnight = fetch_overnight_us()
    cn_flash, flash_src = fetch_cn_flash()
    policy, policy_src = fetch_policy()
    discovery = build_discovery_digest(cn_flash, policy)

    result = {
        'fetched_at': NOW.isoformat(),
        'overnight_us': overnight,
        'cn_flash': cn_flash,
        'policy': policy,
        'discovery': discovery,
        '_meta': {
            'sources_ok': overnight.get('sources_ok', []) + flash_src + policy_src,
            'flash_window_hours': 12,
            'scoring': 'keyword tier critical=95/high=80/medium=60/low=40; +15持仓命中/+8watchlist命中',
            'discovery_note': '产业关键词反查product_tree_map.json,找watchlist/持仓名单外的成分股'
                               f'(树映射{len(TREE_ENTRIES)}条,{len(INDUSTRY_KEYWORDS)}个触发词)',
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

    if discovery:
        print(f'\n【新标的发现 discovery】{len(discovery)}只名单外候选(产业关键词命中产品树,未在watchlist/持仓):')
        for c in discovery[:20]:
            print(f'  {c["name"]}({c["ticker"]}) | 树={c["tree"][:24]} | 节点={c.get("node","-")[:20]} '
                  f'| 触发词={c["matched_keyword"]} | 源=[{c["first_seen_score"]:>3}]{c["first_seen_title"][:36]}')
    else:
        print('\n【新标的发现 discovery】今日无(未命中产业关键词, 或命中的树成分股已全部在watchlist/持仓里)')

    print(f'\n已写入: {OUT_FILE}')


if __name__ == '__main__':
    main()
