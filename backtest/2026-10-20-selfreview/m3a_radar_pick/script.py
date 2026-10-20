#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026-10-20 策略一"题材雷达"选股自查回测 + 今日应用
只读: 不改动 sim-portfolio 任何已有文件, 不下单, 不写 portfolio_state.json
数据: backtest/2026-10-09-theme/ths/*.json (同花顺涨停池逐日, 2025-09-24起)
      data/cn_hk_price_db/a_daily.parquet (A股日线, 覆盖到2026-10-19)
产出: signals.csv / keys.csv / today.md / summary.md (均写入 OUT)
"""
import os, sys, json, glob, re, time, datetime, urllib.request
os.environ['NO_PROXY'] = '*'
import pandas as pd, numpy as np
import pyarrow.dataset as ds

BASE = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio'
THS_DIR = f'{BASE}/backtest/2026-10-09-theme/ths'
OUT = f'{BASE}/backtest/2026-10-20-selfreview/m3a_radar_pick'
PARQUET = f'{BASE}/data/cn_hk_price_db/a_daily.parquet'
os.makedirs(OUT, exist_ok=True)

T_START = pd.Timestamp('2025-09-24')
T_END   = pd.Timestamp('2026-10-16')   # 确认日T的上限(留出卖出窗口, 指令给定)
PX_MAX  = pd.Timestamp('2026-10-19')   # 日线库最后完整交易日
TODAY   = pd.Timestamp('2026-10-20')
YDAY    = pd.Timestamp('2026-10-19')
SPLIT   = pd.Timestamp('2026-04-01')   # 样本内/样本外分割点

print(f'[{datetime.datetime.now()}] 启动, OUT={OUT}')

# ============================================================
# 1. theme.py 口径复制 (不 import 该文件, 避免其模块级代码重算并写parquet)
#    以下 SYN/TOK2/GEN/themes() 逐字复制自
#    backtest/2026-10-09-theme/theme.py (2026-10-16 版, 75行)
# ============================================================
SYN = {
 '固态电池':['固态电池','锂电池','锂电','钠离子电池','钠电池','六氟磷酸锂','电解液','动力电池','负极材料','正极材料','隔膜','铝塑膜','锂电池材料','电池','磷酸铁锂','硅碳负极','复合集流体','电池回收'],
 '农业':['种业','转基因','粮食','农业','生猪养殖','猪肉','农药','化肥','种植业','大豆','玉米','乡村振兴','农产品','粮食安全','生物育种','鸡肉','养殖','饲料','水产','种子','农机','土地流转','农业种植','杂交水稻','钾肥','磷肥'],
 '医药':['创新药','中药','医药','CXO','仿制药','原料药','生物医药','医疗器械','疫苗','流感','减肥药','医药商业','生物制品','化学制药','抗癌','ADC','GLP-1','多肽','合成生物','细胞治疗','基因治疗','医疗','医疗服务','CRO','血液制品','抗生素','创新药出海','BD授权'],
 'PCB':['PCB','印制电路板','PCB概念','高阶HDI','HDI','覆铜板','PCB设备','AI PCB'],
 'AI漫剧短剧':['AI漫剧','AI短剧','微短剧','短剧','短剧游戏','漫剧','互动短剧'],
 'AI制药':['AI医疗','AI制药','AI药物研发','AI医药','AI+医疗','AI诊断','医疗AI','AI药物发现'],
 '冰雪':['冰雪旅游','冰雪经济','冰雪消费','冰雪旅游保障','冰雪工程','制冰系统','哈尔滨景区'],
 '染料':['染料','染料中间体','染料产业链','分散染料','活性染料'],
 '低空经济':['低空经济','飞行汽车','低空智联','低空规划','eVTOL','通航飞机','轻型飞机'],
 'CPO光通信':['CPO','CPO概念','光模块','高速光模块','光通信','光通信测试','硅光','硅光产品','光纤光缆','光探测芯片','光芯片','磷化铟','共封装光学','光器件'],
}
TOK2 = {t:k for k,v in SYN.items() for t in v}
GEN = re.compile('国资|央企|国企|报|预增|扭亏|增长|回购|控制权|定增|股权|摘帽|复牌|次新|减亏|亏损|外销|产能|重组|并购|收购|转让|激励|业绩|涨价|订单|中标|合同|子公司|新股|出海|大客户|海外|高送转|ST|举牌|实控人|分红|借壳|资产注入|上市|增持|减持|签约|投资|合作|扩产|降本|提价|利润|营收|主业|龙头|第一|全球|国内|市占率')

def make_themes_fn(tok2):
    def themes(reason):
        out = set()
        for t in (reason or '').split('+'):
            t = t.strip()
            if not t: continue
            if t in tok2: out.add(tok2[t]); continue
            if 'AI' in t and ('医' in t or '药' in t): out.add('AI制药'); continue
            if re.search('冰雪', t): out.add('冰雪'); continue
            if re.search('染料', t): out.add('染料'); continue
            if re.search('低空|飞行汽车|eVTOL', t): out.add('低空经济'); continue
            if re.search('钙钛矿|光伏|HJT|TOPCon|BC电池|太阳能', t): out.add('光伏'); continue
            if re.search('电池|锂|钠离子|电解液|负极|正极|隔膜|铝塑膜|集流体', t): out.add('固态电池'); continue
            if re.search('种业|育种|制种|种子|粮|玉米|大豆|水稻|小麦|转基因|农业|农产品|化肥|钾肥|磷肥|农药|生猪|猪肉|养殖|饲料|水产|棉花|种植', t): out.add('农业'); continue
            if re.search('药|医|生物|疫苗|CXO|CRO|CDMO|ADC|抗体|细胞|基因治疗|诊断|器械|血液', t): out.add('医药'); continue
            if GEN.search(t): continue
            out.add(t)
        return out
    return themes

THEMES_DEFAULT = make_themes_fn(TOK2)

# 2026-10-20 任务指令: 另报"机器人"并组口径(仅用于step5今日判断, 不改历史回测口径)
SYN_ALT = {k: list(v) for k, v in SYN.items()}
SYN_ALT['机器人'] = ['机器人', '人形机器人', '工业机器人', '机器人概念', '人形机器人概念', '工业机器人产业链']
TOK2_ALT = {t: k for k, v in SYN_ALT.items() for t in v}
THEMES_ALT = make_themes_fn(TOK2_ALT)

# ============================================================
# 2. 读取全部 ths 逐日涨停池 (含 2026-10-20 当天盘中快照)
# ============================================================
files_all = sorted(glob.glob(f'{THS_DIR}/*.json'))
print(f'ths文件数: {len(files_all)}, 范围 {files_all[0][-13:-5]} 到 {files_all[-1][-13:-5]}')

raw_rows = []
for f in files_all:
    dstr = f.split('/')[-1][:8]
    date = pd.Timestamp(f'{dstr[:4]}-{dstr[4:6]}-{dstr[6:]}')
    recs = json.load(open(f))
    for r in recs:
        raw_rows.append({
            'date': date, 'code': str(r['code']).zfill(6), 'name': r.get('name', ''),
            'reason_type': r.get('reason_type', ''),
            'change_rate': r.get('change_rate'),
            'turnover_rate': r.get('turnover_rate'),
            'currency_value': r.get('currency_value'),
            'high_days_value': r.get('high_days_value'),
            'open_num': r.get('open_num'),
        })
RAW = pd.DataFrame(raw_rows)
print(f'RAW 行数: {len(RAW)}, 唯一日期: {RAW.date.nunique()}, 唯一代码: {RAW.code.nunique()}')

# code -> name 最新已知(按日期), 用于ST判定
NAME_HIST = {}
for code, g in RAW.groupby('code'):
    NAME_HIST[code] = sorted(zip(g['date'], g['name']))

def is_st_asof(code, asof_date):
    hist = NAME_HIST.get(code)
    if not hist:
        return False
    name = None
    for d, n in hist:
        if d <= asof_date:
            name = n
        else:
            break
    if name is None:
        name = hist[0][1]
    name = (name or '').strip().lstrip('*').upper()
    return name.startswith('ST')

# ============================================================
# 3. 题材行展开(default口径) -> 全历史(不含今日智能过滤, 含今日盘中快照行)
# ============================================================
def explode_themes(raw_df, themes_fn):
    out = []
    for date, code, reason in zip(raw_df['date'], raw_df['code'], raw_df['reason_type']):
        for th in themes_fn(reason):
            out.append((date, th, code))
    return pd.DataFrame(out, columns=['date', 'theme', 'code'])

THEME_ROWS = explode_themes(RAW, THEMES_DEFAULT)
print(f'THEME_ROWS(default) 行数: {len(THEME_ROWS)}, 唯一题材: {THEME_ROWS.theme.nunique()}')

days_all = sorted(RAW['date'].unique())  # 权威交易日轴(来自ths文件本身, 含今日盘中)
cnt = THEME_ROWS.groupby(['date', 'theme'])['code'].nunique().unstack(fill_value=0).reindex(days_all, fill_value=0)
rk = cnt.rank(axis=1, ascending=False, method='min')

days_hist = [d for d in days_all if d <= PX_MAX]  # 不含今日盘中快照, 用于历史确认日扫描
print(f'历史交易日(含ths数据) n={len(days_hist)}, 今日(含)总天数 n={len(days_all)}')

# ============================================================
# 4. 价格数据: pyarrow filters 按日期读取(不整表读), 透视为宽表
# ============================================================
d0 = pd.Timestamp('2025-07-01')
dataset = ds.dataset(PARQUET, format='parquet')
tbl = dataset.to_table(
    filter=(ds.field('date') >= ds.scalar(d0)) & (ds.field('date') <= ds.scalar(PX_MAX))
)
PX = tbl.to_pandas()
print(f'价格库切片行数: {len(PX)}, 代码数: {PX.ticker.nunique()}, 日期范围: {PX.date.min()} ~ {PX.date.max()}')

close_w = PX.pivot(index='date', columns='ticker', values='close').sort_index()
adj_w   = PX.pivot(index='date', columns='ticker', values='adj_close').sort_index()
open_w  = PX.pivot(index='date', columns='ticker', values='open').sort_index()
high_w  = PX.pivot(index='date', columns='ticker', values='high').sort_index()
low_w   = PX.pivot(index='date', columns='ticker', values='low').sort_index()
amt_w   = PX.pivot(index='date', columns='ticker', values='amount').sort_index()
osh_w   = PX.pivot(index='date', columns='ticker', values='oshare').sort_index()

PRICE_DAYS = list(close_w.index)
PRICE_DAYS_IDX = {d: i for i, d in enumerate(PRICE_DAYS)}
TICKER_SET = set(close_w.columns)

def code_to_ticker(code):
    c = str(code).zfill(6)
    p2 = c[:2]
    if c[0] in ('4', '8') or p2 == '92':
        suf = 'BJ'
    elif c[0] in ('6', '5'):
        suf = 'SH'
    elif c[0] in ('0', '3'):
        suf = 'SZ'
    else:
        return None
    return f'{c}.{suf}'

def limit_pct(code, asof_date):
    c = str(code).zfill(6)
    p2 = c[:2]
    if c[0] in ('4', '8') or p2 == '92':
        return 0.30
    if p2 in ('30', '68'):
        return 0.20
    if p2 in ('60', '00'):
        if is_st_asof(code, asof_date):
            return 0.05 if asof_date < pd.Timestamp('2026-07-06') else 0.10
        return 0.10
    return 0.10

def prev_trading_day(date):
    pos = PRICE_DAYS_IDX.get(date)
    if pos is None or pos == 0:
        return None
    return PRICE_DAYS[pos - 1]

def px_get(w, date, ticker):
    if date not in w.index or ticker not in w.columns:
        return np.nan
    return w.at[date, ticker]

def is_sealed_at_close(code, date):
    """T日收盘是否封住涨停(按不复权close/high对前收盘公式判定, 不信任ths自身标记)"""
    ticker = code_to_ticker(code)
    if ticker is None or ticker not in TICKER_SET:
        return None
    pdy = prev_trading_day(date)
    if pdy is None:
        return None
    prevc = px_get(close_w, pdy, ticker)
    c = px_get(close_w, date, ticker)
    h = px_get(high_w, date, ticker)
    if pd.isna(prevc) or pd.isna(c) or pd.isna(h) or prevc == 0:
        return None
    pct = limit_pct(code, date)
    thresh = round(prevc * (1 + pct), 2) - 0.005
    return bool(c >= thresh and c == h)

def is_yizi(code, date):
    """开盘即一字涨停(open=high=low=涨停价), 当天买不进"""
    ticker = code_to_ticker(code)
    if ticker is None or ticker not in TICKER_SET:
        return None
    sealed = is_sealed_at_close(code, date)
    if sealed is not True:
        return False
    o = px_get(open_w, date, ticker); h = px_get(high_w, date, ticker); l = px_get(low_w, date, ticker)
    if pd.isna(o) or pd.isna(h) or pd.isna(l):
        return None
    return bool(o == h == l)

print(f'[{datetime.datetime.now()}] 价格宽表就绪: {close_w.shape}, 交易日轴 n={len(PRICE_DAYS)}')

# ============================================================
# 5. 确认日检测(现行规则, 不加新题材过滤, 不加2板条件):
#    题材 T-1 与 T 两天涨停只数均排全市场前3且每天>=5只
# ============================================================
K, M = 3, 5
confirmations = []
for i in range(1, len(days_hist)):
    t, t1 = days_hist[i], days_hist[i - 1]
    if t < T_START or t > T_END:
        continue
    ok = (rk.loc[t] <= K) & (rk.loc[t1] <= K) & (cnt.loc[t] >= M) & (cnt.loc[t1] >= M)
    for th in ok[ok].index:
        confirmations.append({'date': t, 'theme': th, 'c_t1': int(cnt.loc[t1, th]), 'c_t': int(cnt.loc[t, th])})
CONF = pd.DataFrame(confirmations).sort_values(['date', 'theme']).reset_index(drop=True)
print(f'确认日×题材 实例数: {len(CONF)} (范围 {T_START.date()} 到 {T_END.date()})')
print(f'唯一确认日天数: {CONF.date.nunique()}, 唯一题材数: {CONF.theme.nunique()}')

# ============================================================
# 6. 题材成员池(T日及之前60个交易日内被该题材标记过的代码, 只用ths轴)
# ============================================================
THEME_SUB_CACHE = {}  # theme -> 排序后的 (date, code) 列表, 加速窗口切片
DAYS_ALL_IDX = {d: i for i, d in enumerate(days_all)}

def get_member_window(theme, T):
    """返回(members去重列表, 该窗口内THEME_ROWS子集df用于计数)"""
    if theme not in THEME_SUB_CACHE:
        sub = THEME_ROWS[THEME_ROWS.theme == theme].sort_values('date')
        THEME_SUB_CACHE[theme] = sub
    sub = THEME_SUB_CACHE[theme]
    i = DAYS_ALL_IDX.get(T)
    if i is None:
        return [], sub.iloc[0:0]
    lo_i = max(0, i - 59)
    lo_date, hi_date = days_all[lo_i], T
    win = sub[(sub.date >= lo_date) & (sub.date <= hi_date)]
    return sorted(win.code.unique()), win

def buyable_pool_at(theme, T):
    """T日收盘未封住涨停的题材成员(可买池)"""
    members, win = get_member_window(theme, T)
    pool = []
    for code in members:
        ticker = code_to_ticker(code)
        if ticker is None or ticker not in TICKER_SET:
            continue
        c = px_get(close_w, T, ticker)
        if pd.isna(c):
            continue
        sealed = is_sealed_at_close(code, T)
        if sealed is True:
            continue
        pool.append(code)
    return pool, members, win

print(f'[{datetime.datetime.now()}] 确认日检测完成')

# ============================================================
# 7. 持有期模拟: 买T日收盘(近似14:30) -> 持有到T+4交易日收盘(近似14:55),
#    期间收盘跌破买价7%止损; 多日收益用adj_close(如遇除权除息更准确,
#    止损判定与收益口径统一用adj_close比值, 避免两套口径互相矛盾)
# ============================================================
BENCH_CACHE = {}

def benchmark_median(T, horizon=4):
    key = (T, horizon)
    if key in BENCH_CACHE:
        return BENCH_CACHE[key]
    pos = PRICE_DAYS_IDX.get(T)
    if pos is None or pos + horizon >= len(PRICE_DAYS):
        BENCH_CACHE[key] = np.nan
        return np.nan
    day_h = PRICE_DAYS[pos + horizon]
    r = adj_w.loc[day_h] / adj_w.loc[T] - 1
    med = r.median(skipna=True)
    BENCH_CACHE[key] = med
    return med

def simulate_trade(ticker, T, stop=0.07, horizon=4):
    """返回 dict: ret(最终收益,若不完整为None), exit_k, reason, incomplete(bool)"""
    pos = PRICE_DAYS_IDX.get(T)
    if pos is None or ticker not in TICKER_SET:
        return {'ret': None, 'exit_k': None, 'reason': 'no_entry_data', 'incomplete': True}
    entry = px_get(adj_w, T, ticker)
    if pd.isna(entry) or entry == 0:
        return {'ret': None, 'exit_k': None, 'reason': 'no_entry_data', 'incomplete': True}
    if pos + horizon >= len(PRICE_DAYS):
        return {'ret': None, 'exit_k': None, 'reason': 'sell_data_incomplete', 'incomplete': True}
    last_ratio = None
    for k in range(1, horizon + 1):
        day_k = PRICE_DAYS[pos + k]
        px_k = px_get(adj_w, day_k, ticker)
        if pd.isna(px_k):
            continue  # 停牌等, 跳过该日继续查下一日
        ratio = px_k / entry - 1
        last_ratio = ratio
        if ratio <= -stop and k < horizon:
            return {'ret': ratio, 'exit_k': k, 'reason': 'stop_7pct', 'incomplete': False}
        if k == horizon:
            reason = 'stop_7pct' if ratio <= -stop else 'scheduled_T4'
            return {'ret': ratio, 'exit_k': k, 'reason': reason, 'incomplete': False}
    # 一直停牌到horizon都没有有效价格
    if last_ratio is None:
        return {'ret': None, 'exit_k': None, 'reason': 'all_suspended', 'incomplete': True}
    return {'ret': last_ratio, 'exit_k': horizon, 'reason': 'scheduled_T4', 'incomplete': False}

print(f'[{datetime.datetime.now()}] 收益模拟函数就绪')

# ============================================================
# 8. 逐个确认实例: 建可买池 + 计算选股键特征 + 模拟交易
# ============================================================
def feature_row(code, T):
    ticker = code_to_ticker(code)
    c = px_get(close_w, T, ticker)
    pdy = prev_trading_day(T)
    prevc = px_get(close_w, pdy, ticker) if pdy is not None else np.nan
    pct_t = (c / prevc - 1) if (pd.notna(c) and pd.notna(prevc) and prevc != 0) else np.nan
    amt = px_get(amt_w, T, ticker)
    osh = px_get(osh_w, T, ticker)
    fcap = (osh * c) if (pd.notna(osh) and pd.notna(c)) else np.nan
    # 前一日涨幅(T-1相对T-2)
    if pdy is not None:
        pdy2 = prev_trading_day(pdy)
        c1 = px_get(close_w, pdy, ticker)
        c2 = px_get(close_w, pdy2, ticker) if pdy2 is not None else np.nan
        pct_tm1 = (c1 / c2 - 1) if (pd.notna(c1) and pd.notna(c2) and c2 != 0) else np.nan
    else:
        pct_tm1 = np.nan
    return {'code': code, 'ticker': ticker, 'pct_t': pct_t, 'amount_t': amt,
            'float_cap_t': fcap, 'pct_tm1': pct_tm1}

INSTANCES = []  # 每个确认实例的完整上下文(含可买池+特征+每个候选的模拟收益, 供后续按键取数)
empty_pool_count = 0
for _, row in CONF.iterrows():
    T, theme = row['date'], row['theme']
    pool, members, win = buyable_pool_at(theme, T)
    if len(pool) == 0:
        empty_pool_count += 1
        INSTANCES.append({'date': T, 'theme': theme, 'c_t1': row['c_t1'], 'c_t': row['c_t'],
                           'pool_size': 0, 'member_size': len(members), 'pool': [], 'feats': {}, 'sims': {}})
        continue
    feats = {}
    for code in pool:
        f = feature_row(code, T)
        f['count60'] = int((win.code == code).sum())
        feats[code] = f
    sims = {code: simulate_trade(feats[code]['ticker'], T) for code in pool}
    INSTANCES.append({'date': T, 'theme': theme, 'c_t1': row['c_t1'], 'c_t': row['c_t'],
                       'pool_size': len(pool), 'member_size': len(members),
                       'pool': pool, 'feats': feats, 'sims': sims})

print(f'[{datetime.datetime.now()}] 全部 {len(INSTANCES)} 个确认实例的可买池+模拟完成; 空池实例数: {empty_pool_count}')

# ============================================================
# 9. 选股键定义 + 排序取数 + 汇总统计
# ============================================================
KEYS = [
    ('T日涨幅最高的未封板股', 'pct_t', False),
    ('T日成交额最大', 'amount_t', False),
    ('流通市值最大', 'float_cap_t', False),
    ('流通市值最小', 'float_cap_t', True),
    ('过去60日该题材涨停次数最多(辨识度)', 'count60', False),
    ('前一日涨幅最高', 'pct_tm1', False),
]

def rank_pool(inst, feat_name, ascending, exclude_neg_tm1=False):
    pool = inst['pool']; feats = inst['feats']
    cands = []
    for code in pool:
        f = feats[code]
        if exclude_neg_tm1:
            v_tm1 = f.get('pct_tm1')
            if v_tm1 is None or pd.isna(v_tm1) or v_tm1 < 0:
                continue
        v = f.get(feat_name)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        cands.append((code, v))
    if not cands:
        return []
    cands.sort(key=lambda x: x[1], reverse=(not ascending))
    return [c for c, v in cands]

def build_key_records(instances, exclude_neg_tm1=False):
    records = []
    for inst in instances:
        if inst['pool_size'] == 0:
            continue
        T, theme = inst['date'], inst['theme']
        bench = benchmark_median(T)
        sims = inst['sims']; feats = inst['feats']
        pool = inst['pool']
        pool_f = pool
        if exclude_neg_tm1:
            pool_f = [c for c in pool if pd.notna(feats[c]['pct_tm1']) and feats[c]['pct_tm1'] >= 0]
        if pool_f:
            rets = [sims[c]['ret'] for c in pool_f if sims[c]['ret'] is not None]
            if rets:
                stopflags = [sims[c]['reason'] == 'stop_7pct' for c in pool_f if sims[c]['ret'] is not None]
                records.append({'key': '全池等权平均(基准)', 'variant': 'all_ew', 'date': T, 'theme': theme,
                                 'ret': float(np.mean(rets)), 'stop': float(np.mean(stopflags)), 'bench': bench,
                                 'n_in_group': len(rets)})
        for key_name, feat_name, ascending in KEYS:
            order = rank_pool(inst, feat_name, ascending, exclude_neg_tm1)
            if not order:
                continue
            top1 = order[0]
            if sims[top1]['ret'] is not None:
                records.append({'key': key_name, 'variant': 'top1', 'date': T, 'theme': theme,
                                 'ret': sims[top1]['ret'], 'stop': float(sims[top1]['reason'] == 'stop_7pct'),
                                 'bench': bench, 'n_in_group': 1})
            top2 = order[:2]
            rets2 = [sims[c]['ret'] for c in top2 if sims[c]['ret'] is not None]
            if rets2:
                stopflags2 = [sims[c]['reason'] == 'stop_7pct' for c in top2 if sims[c]['ret'] is not None]
                records.append({'key': key_name, 'variant': 'top2_ew', 'date': T, 'theme': theme,
                                 'ret': float(np.mean(rets2)), 'stop': float(np.mean(stopflags2)), 'bench': bench,
                                 'n_in_group': len(rets2)})
    return pd.DataFrame(records)

def aggregate_keys(records_df, sample_label, filter_label):
    if records_df.empty:
        return pd.DataFrame()
    out = []
    for (key, variant), g in records_df.groupby(['key', 'variant']):
        g_bench = g.dropna(subset=['bench'])
        excess = (g_bench.ret - g_bench.bench).mean() if len(g_bench) else np.nan
        out.append({
            'sample': sample_label, 'filter': filter_label, 'key': key, 'variant': variant,
            'n': len(g), 'mean_ret': g.ret.mean(), 'median_ret': g.ret.median(),
            'win_rate': (g.ret > 0).mean(), 'stop_rate': g.stop.mean(),
            'excess_vs_mkt_median': excess, 'n_for_excess': len(g_bench),
        })
    return pd.DataFrame(out)

REC_BASE = build_key_records(INSTANCES, exclude_neg_tm1=False)
REC_EX_DECLINE = build_key_records(INSTANCES, exclude_neg_tm1=True)
print(f'[{datetime.datetime.now()}] key记录: base={len(REC_BASE)}条, ex_prev_decline={len(REC_EX_DECLINE)}条')

KEYS_ALL = []
for rec_df, filt in [(REC_BASE, 'base'), (REC_EX_DECLINE, 'ex_prev_decline')]:
    KEYS_ALL.append(aggregate_keys(rec_df, 'all', filt))
    KEYS_ALL.append(aggregate_keys(rec_df[rec_df.date < SPLIT], 'in_sample_0924_0331', filt))
    KEYS_ALL.append(aggregate_keys(rec_df[rec_df.date >= SPLIT], 'out_sample_0401_1016', filt))
KEYS_DF = pd.concat(KEYS_ALL, ignore_index=True)
print(f'[{datetime.datetime.now()}] keys汇总表行数: {len(KEYS_DF)}')

# ============================================================
# 10. 对照口径: T+1开盘买T日该题材已涨停的股(T+1一字剔除)
#     卖出按现行规则应用于新买入日T+1(即T+1持有到其第4个交易日收盘)
#     ⛔简化说明: 用不复权价(open/close)算收益, 不按样本内外拆分,
#     仅作整体对照(任务要求"另报", 非要求与前述6键同等拆分)
# ============================================================
def simulate_trade_open_raw(ticker, T1, stop=0.07, horizon=4):
    pos = PRICE_DAYS_IDX.get(T1)
    if pos is None or ticker not in TICKER_SET:
        return None
    entry = px_get(open_w, T1, ticker)
    if pd.isna(entry) or entry == 0:
        return None
    if pos + horizon >= len(PRICE_DAYS):
        return None
    last_ratio = None
    for k in range(0, horizon + 1):
        day_k = PRICE_DAYS[pos + k] if k > 0 else T1
        px_k = px_get(close_w, day_k, ticker) if k > 0 else entry
        if pd.isna(px_k):
            continue
        ratio = px_k / entry - 1
        last_ratio = ratio
        if k == 0:
            continue
        if ratio <= -stop and k < horizon:
            return {'ret': ratio, 'reason': 'stop_7pct'}
        if k == horizon:
            return {'ret': ratio, 'reason': 'stop_7pct' if ratio <= -stop else 'scheduled_T4'}
    return {'ret': last_ratio, 'reason': 'scheduled_T4'} if last_ratio is not None else None

alt_records = []
alt_skipped_yizi = 0
for inst in INSTANCES:
    T, theme = inst['date'], inst['theme']
    members, win = get_member_window(theme, T)
    sealed_codes = [c for c in members if is_sealed_at_close(c, T) is True]
    if not sealed_codes:
        continue
    pos = PRICE_DAYS_IDX.get(T)
    if pos is None or pos + 1 >= len(PRICE_DAYS):
        continue
    T1 = PRICE_DAYS[pos + 1]
    for code in sealed_codes:
        ticker = code_to_ticker(code)
        if ticker is None or ticker not in TICKER_SET:
            continue
        yizi = is_yizi(code, T1)
        if yizi is True:
            alt_skipped_yizi += 1
            continue
        sim = simulate_trade_open_raw(ticker, T1)
        if sim is None:
            continue
        bench = benchmark_median(T1)
        alt_records.append({'ret': sim['ret'], 'stop': sim['reason'] == 'stop_7pct', 'bench': bench})
ALT_DF = pd.DataFrame(alt_records)
if len(ALT_DF):
    ab = ALT_DF.dropna(subset=['bench'])
    alt_row = pd.DataFrame([{
        'sample': 'all', 'filter': 'base', 'key': 'T+1开盘买T日已涨停股(一字剔除,不复权价简化口径)',
        'variant': 'all_ew', 'n': len(ALT_DF), 'mean_ret': ALT_DF.ret.mean(), 'median_ret': ALT_DF.ret.median(),
        'win_rate': (ALT_DF.ret > 0).mean(), 'stop_rate': ALT_DF.stop.mean(),
        'excess_vs_mkt_median': (ab.ret - ab.bench).mean(), 'n_for_excess': len(ab),
    }])
    KEYS_DF = pd.concat([KEYS_DF, alt_row], ignore_index=True)
print(f'[{datetime.datetime.now()}] T+1开盘对照口径: n={len(ALT_DF)}, 一字剔除数={alt_skipped_yizi}')

# ============================================================
# 11. 写 signals.csv (确认日×题材实例, part1+part4) 与 keys.csv (part2+part3)
# ============================================================
sig_rows = []
for inst in INSTANCES:
    T = inst['date']
    sample = 'in_sample_0924_0331' if T < SPLIT else 'out_sample_0401_1016'
    has_fwd = T in PRICE_DAYS_IDX and (PRICE_DAYS_IDX[T] + 4 < len(PRICE_DAYS))
    baseline_ret = np.nan
    if inst['pool_size'] > 0:
        rets = [inst['sims'][c]['ret'] for c in inst['pool'] if inst['sims'][c]['ret'] is not None]
        if rets:
            baseline_ret = float(np.mean(rets))
    sig_rows.append({
        'date': T.strftime('%Y-%m-%d'), 'theme': inst['theme'], 'c_theme_t1': inst['c_t1'], 'c_theme_t': inst['c_t'],
        'member_size_60d': inst['member_size'], 'buyable_pool_size': inst['pool_size'],
        'pool_empty': inst['pool_size'] == 0, 'fwd_T4_data_available': has_fwd,
        'sample_period': sample, 'pool_all_ew_return': baseline_ret,
    })
SIGNALS_DF = pd.DataFrame(sig_rows).sort_values(['date', 'theme'])
SIGNALS_DF.to_csv(f'{OUT}/signals.csv', index=False, encoding='utf-8-sig')
print(f'[{datetime.datetime.now()}] signals.csv 已写入, {len(SIGNALS_DF)}行')

KEYS_DF.to_csv(f'{OUT}/keys.csv', index=False, encoding='utf-8-sig')
print(f'[{datetime.datetime.now()}] keys.csv 已写入, {len(KEYS_DF)}行')

# part4 文字统计(供summary.md引用)
n_total = len(SIGNALS_DF)
n_empty = int(SIGNALS_DF.pool_empty.sum())
pool_stats = SIGNALS_DF.loc[~SIGNALS_DF.pool_empty, 'buyable_pool_size'].describe()
print(f'part4: 确认实例总数={n_total}, 空池数={n_empty}, 非空池pool_size中位={pool_stats["50%"]:.0f} 均值={pool_stats["mean"]:.1f} 最小={pool_stats["min"]:.0f} 最大={pool_stats["max"]:.0f}')

# ============================================================
# 12. 稳健键判定(样本内/样本外都靠前) + part5 今日应用
# ============================================================
ROBUST_KEY_NAME = '流通市值最小'  # 由上面in/out-sample对比确定(两段excess均为正且接近: +1.28pp/+1.26pp, 唯一两段一致为正的键)

def explode_themes_fn(raw_df, themes_fn):
    out = []
    for date, code, reason in zip(raw_df['date'], raw_df['code'], raw_df['reason_type']):
        for th in themes_fn(reason):
            out.append((date, th, code))
    return pd.DataFrame(out, columns=['date', 'theme', 'code'])

THEME_ROWS_ALT = explode_themes_fn(RAW, THEMES_ALT)

def day_theme_counts(raw_day, themes_fn):
    rows = []
    for code, reason in zip(raw_day.code, raw_day.reason_type):
        for th in themes_fn(reason):
            rows.append((th, code))
    d = pd.DataFrame(rows, columns=['theme', 'code'])
    if len(d) == 0:
        return pd.Series(dtype=int)
    return d.groupby('theme').code.nunique().sort_values(ascending=False)

def check_confirm_2day(cnt_t1, rk_t1, cnt_t, rk_t, K=3, M=5):
    out = []
    for th in set(cnt_t1.index) | set(cnt_t.index):
        c1, c0 = cnt_t1.get(th, 0), cnt_t.get(th, 0)
        r1, r0 = rk_t1.get(th, 9999), rk_t.get(th, 9999)
        if c1 >= M and c0 >= M and r1 <= K and r0 <= K:
            out.append({'theme': th, 'c_t1': int(c1), 'c_t': int(c0), 'rk_t1': float(r1), 'rk_t': float(r0)})
    return pd.DataFrame(out).sort_values('c_t', ascending=False) if out else pd.DataFrame()

# 口径A: 默认(人形机器人/机器人/工业机器人互不并组), 复用已有全历史 cnt/rk
conf_default = check_confirm_2day(cnt.loc[YDAY], rk.loc[YDAY], cnt.loc[TODAY], rk.loc[TODAY])
# 口径B: 并组(本任务要求的"机器人"合并口径), 只需当天两日
RAW_T1, RAW_T = RAW[RAW.date == YDAY], RAW[RAW.date == TODAY]
cnt_t1_alt, cnt_t_alt = day_theme_counts(RAW_T1, THEMES_ALT), day_theme_counts(RAW_T, THEMES_ALT)
rk_t1_alt, rk_t_alt = cnt_t1_alt.rank(ascending=False, method='min'), cnt_t_alt.rank(ascending=False, method='min')
conf_alt = check_confirm_2day(cnt_t1_alt, rk_t1_alt, cnt_t_alt, rk_t_alt)
print(f'[{datetime.datetime.now()}] 今日确认(默认口径): \n{conf_default}')
print(f'[{datetime.datetime.now()}] 今日确认(并组口径): \n{conf_alt}')

TODAY_CONFIRMED = len(conf_alt) > 0
TODAY_THEME_ALT = conf_alt.iloc[0]['theme'] if TODAY_CONFIRMED else None

def tencent_fetch(codes, chunk=60):
    def c2q(code):
        c = str(code).zfill(6)
        if c[0] in ('4', '8') or c[:2] == '92':
            return 'bj' + c
        if c[0] in ('6', '5'):
            return 'sh' + c
        if c[0] in ('0', '3'):
            return 'sz' + c
        return None
    qcodes = [c2q(c) for c in codes]
    qcodes = [q for q in qcodes if q]
    texts = []
    for i in range(0, len(qcodes), chunk):
        batch = qcodes[i:i + chunk]
        url = 'http://qt.gtimg.cn/q=' + ','.join(batch)
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            texts.append(resp.read().decode('gbk', errors='ignore'))
    fetch_ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    recs = {}
    for seg in '\n'.join(texts).split(';'):
        seg = seg.strip()
        if not seg or '=' not in seg:
            continue
        key, val = seg.split('=', 1)
        val = val.strip().strip('"')
        if not val:
            continue
        parts = val.split('~')
        if len(parts) < 48:
            continue
        code = key.split('_')[-1][2:]
        try:
            recs[code] = {
                'code': code, 'name': parts[1],
                'price': float(parts[3]) if parts[3] else None,
                'prev_close': float(parts[4]) if parts[4] else None,
                'pct_chg': float(parts[32]) if parts[32] else None,
                'amount_wan': float(parts[37]) if parts[37] else None,
                'float_cap_yi': float(parts[44]) if parts[44] else None,
                'limit_price': float(parts[47]) if parts[47] else None,
            }
        except ValueError:
            continue
    return recs, fetch_ts

today_table_md = '(今日题材未确认, 无需出票)'
mover_table_md = ''
n_members = n_sealed = n_eligible = n_st = 0
fetch_ts = None

if TODAY_CONFIRMED:
    i_today = DAYS_ALL_IDX[TODAY]
    lo = max(0, i_today - 59)
    sub_alt = THEME_ROWS_ALT[THEME_ROWS_ALT.theme == TODAY_THEME_ALT]
    win_alt = sub_alt[(sub_alt.date >= days_all[lo]) & (sub_alt.date <= TODAY)]
    members_today = sorted(win_alt.code.unique())
    count60_today = win_alt.groupby('code').size().to_dict()
    n_members = len(members_today)

    quotes, fetch_ts = tencent_fetch(members_today)
    qdf = pd.DataFrame(quotes.values())
    qdf['count60'] = qdf.code.map(count60_today).fillna(0).astype(int)
    qdf['is_st'] = qdf.name.fillna('').str.upper().str.lstrip('*').str.startswith('ST')
    qdf['sealed_now'] = qdf.limit_price.notna() & (qdf.price >= qdf.limit_price - 0.005)
    n_st, n_sealed = int(qdf.is_st.sum()), int(qdf.sealed_now.sum())

    # B策略持仓剔除(读b_book.json只读, 不修改)
    try:
        b_book = json.load(open(f'{BASE}/data/b_book.json'))
        b_codes = {p.get('ticker', p.get('code', '')) for p in b_book.get('positions', [])}
    except Exception:
        b_codes = set()

    eligible = qdf[(~qdf.is_st) & (~qdf.sealed_now) & qdf.float_cap_yi.notna() & (~qdf.code.isin(b_codes))].copy()
    n_eligible = len(eligible)

    # 前一日(T-1)涨跌: 用价格库算, 与回测口径一致
    def prevday_pct(code):
        f = feature_row(code, YDAY)
        return f['pct_t']
    eligible['pct_prevday'] = eligible.code.map(prevday_pct)

    top5 = eligible.sort_values('float_cap_yi').head(5)
    lines = ['| 排名 | 代码 | 名称 | 现价 | 今日涨跌% | 成交额(万元) | 流通市值(亿) | 60日涨停次数 | 前一日涨跌% |',
             '|---|---|---|---|---|---|---|---|---|']
    for rank_i, (_, r) in enumerate(top5.iterrows(), 1):
        lines.append(f"| {rank_i} | {r['code']} | {r['name']} | {r['price']:.2f} | {r['pct_chg']:+.2f} | "
                      f"{r['amount_wan']:,.0f} | {r['float_cap_yi']:.2f} | {r['count60']} | {r['pct_prevday']*100:+.2f} |")
    today_table_md = '\n'.join(lines)

    mover = eligible.sort_values('pct_chg', ascending=False).head(2)
    mlines = ['| 代码 | 名称 | 现价 | 今日涨跌% | 流通市值(亿) |', '|---|---|---|---|---|']
    for _, r in mover.iterrows():
        mlines.append(f"| {r['code']} | {r['name']} | {r['price']:.2f} | {r['pct_chg']:+.2f} | {r['float_cap_yi']:.2f} |")
    mover_table_md = '\n'.join(mlines)

print(f'[{datetime.datetime.now()}] step5完成: 确认={TODAY_CONFIRMED}, 题材={TODAY_THEME_ALT}, 成员={n_members}, 封板剔除={n_sealed}, ST={n_st}, 合格候选={n_eligible}')

# ============================================================
# 13. 生成/覆盖 today.md (与本次人工复核版本口径一致, 供脚本复跑时自动更新)
# ============================================================
today_md = f"""# 2026-10-20 题材雷达今日应用(脚本自动生成版, 取数时刻 {fetch_ts})

默认口径确认结果:

{conf_default.to_string(index=False) if len(conf_default) else '(无)'}

并组(机器人合并)口径确认结果:

{conf_alt.to_string(index=False) if len(conf_alt) else '(无)'}

今日确认: {TODAY_CONFIRMED}, 题材(并组口径): {TODAY_THEME_ALT}
题材60日成员数: {n_members}, 其中当前已封板剔除: {n_sealed}, ST剔除: {n_st}, 合格候选: {n_eligible}

## 按最稳健键(流通市值最小)排序前5

{today_table_md}

## 对照: 若按"T日涨幅最高的未封板股"(回测里样本外表现最差的键)

{mover_table_md}

⛔ 本文件为脚本自动生成版, 用于复核/复跑验证; 当天实际提交给Buwen决策参考的叙述版本见同目录 today.md 的人工复核版(若两者数值不一致以本次脚本重跑的时刻更新为准, 因为市场在变化)。
"""
with open(f'{OUT}/today_autogen.md', 'w') as f:
    f.write(today_md)
print(f'[{datetime.datetime.now()}] today_autogen.md 已写入(机器可重跑校验版, 不覆盖人工叙述版today.md)')
print(f'[{datetime.datetime.now()}] 全部完成')


