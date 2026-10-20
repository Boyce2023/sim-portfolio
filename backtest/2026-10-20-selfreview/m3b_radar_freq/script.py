#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
m3b_radar_freq — 策略一"雷达规则"信号频率诊断
问题: 策略一为什么很少买 —— 是雷达规则本身信号少, 还是我执行的少。

只读脚本: 不修改 sim-portfolio 任何既有文件, 不下单。
数据: backtest/2026-10-09-theme/ths/*.json (同花顺涨停池逐日原始数据,
      themes()/SYN/GEN 逐字从 theme.py 读源码复制, 未 import 该模块,
      避免触发其 run()/to_parquet 的重算写盘)。
覆盖: 2025-09-24 ~ 2026-10-19 (今天 10-20 盘中数据不收盘, 不纳入)。
"""
import json, glob, re, os, sys
import pandas as pd, numpy as np

THEME_DIR = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-10-09-theme'
OUT = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-10-20-selfreview/m3b_radar_freq'
PRICE_DB = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet'
PORTFOLIO = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json'
LEDGER = os.path.expanduser('~/.claude/nexus/tasks/astock.jsonl')
CUTOFF = '20261019'  # 今天(10-20)盘中, 数据未收盘, 不纳入分析

os.makedirs(OUT, exist_ok=True)

# ============================================================
# 1. themes()/SYN/GEN — 逐字取自 theme.py 源码(读源码复用, 未 import)
# ============================================================
SYN = {
 '固态电池': ['固态电池', '锂电池', '锂电', '钠离子电池', '钠电池', '六氟磷酸锂', '电解液', '动力电池', '负极材料', '正极材料', '隔膜', '铝塑膜', '锂电池材料', '电池', '磷酸铁锂', '硅碳负极', '复合集流体', '电池回收'],
 '农业': ['种业', '转基因', '粮食', '农业', '生猪养殖', '猪肉', '农药', '化肥', '种植业', '大豆', '玉米', '乡村振兴', '农产品', '粮食安全', '生物育种', '鸡肉', '养殖', '饲料', '水产', '种子', '农机', '土地流转', '农业种植', '杂交水稻', '钾肥', '磷肥'],
 '医药': ['创新药', '中药', '医药', 'CXO', '仿制药', '原料药', '生物医药', '医疗器械', '疫苗', '流感', '减肥药', '医药商业', '生物制品', '化学制药', '抗癌', 'ADC', 'GLP-1', '多肽', '合成生物', '细胞治疗', '基因治疗', '医疗', '医疗服务', 'CRO', '血液制品', '抗生素', '创新药出海', 'BD授权'],
 'PCB': ['PCB', '印制电路板', 'PCB概念', '高阶HDI', 'HDI', '覆铜板', 'PCB设备', 'AI PCB'],
 'AI漫剧短剧': ['AI漫剧', 'AI短剧', '微短剧', '短剧', '短剧游戏', '漫剧', '互动短剧'],
 'AI制药': ['AI医疗', 'AI制药', 'AI药物研发', 'AI医药', 'AI+医疗', 'AI诊断', '医疗AI', 'AI药物发现'],
 '冰雪': ['冰雪旅游', '冰雪经济', '冰雪消费', '冰雪旅游保障', '冰雪工程', '制冰系统', '哈尔滨景区'],
 '染料': ['染料', '染料中间体', '染料产业链', '分散染料', '活性染料'],
 '低空经济': ['低空经济', '飞行汽车', '低空智联', '低空规划', 'eVTOL', '通航飞机', '轻型飞机'],
 'CPO光通信': ['CPO', 'CPO概念', '光模块', '高速光模块', '光通信', '光通信测试', '硅光', '硅光产品', '光纤光缆', '光探测芯片', '光芯片', '磷化铟', '共封装光学', '光器件'],
}
TOK2 = {t: k for k, v in SYN.items() for t in v}
GEN = re.compile('国资|央企|国企|报|预增|扭亏|增长|回购|控制权|定增|股权|摘帽|复牌|次新|减亏|亏损|外销|产能|重组|并购|收购|转让|激励|业绩|涨价|订单|中标|合同|子公司|新股|出海|大客户|海外|高送转|ST|举牌|实控人|分红|借壳|资产注入|上市|增持|减持|签约|投资|合作|扩产|降本|提价|利润|营收|主业|龙头|第一|全球|国内|市占率')


def themes(reason):
    out = set()
    for t in (reason or '').split('+'):
        t = t.strip()
        if not t:
            continue
        if t in TOK2:
            out.add(TOK2[t]); continue
        if 'AI' in t and ('医' in t or '药' in t):
            out.add('AI制药'); continue
        if re.search('冰雪', t):
            out.add('冰雪'); continue
        if re.search('染料', t):
            out.add('染料'); continue
        if re.search('低空|飞行汽车|eVTOL', t):
            out.add('低空经济'); continue
        if re.search('钙钛矿|光伏|HJT|TOPCon|BC电池|太阳能', t):
            out.add('光伏'); continue
        if re.search('电池|锂|钠离子|电解液|负极|正极|隔膜|铝塑膜|集流体', t):
            out.add('固态电池'); continue
        if re.search('种业|育种|制种|种子|粮|玉米|大豆|水稻|小麦|转基因|农业|农产品|化肥|钾肥|磷肥|农药|生猪|猪肉|养殖|饲料|水产|棉花|种植', t):
            out.add('农业'); continue
        if re.search('药|医|生物|疫苗|CXO|CRO|CDMO|ADC|抗体|细胞|基因治疗|诊断|器械|血液', t):
            out.add('医药'); continue
        if GEN.search(t):
            continue
        out.add(t)
    return out


# ============================================================
# 2. 读 ths/*.json, 构建 date x theme 的涨停只数矩阵
# ============================================================
rows = []
daily_total_zt = {}
for f in sorted(glob.glob(f'{THEME_DIR}/ths/*.json')):
    d = os.path.basename(f)[:8]
    if d > CUTOFF:
        continue
    data = json.load(open(f))
    daily_total_zt[d] = len(data)
    for r in data:
        hd = r.get('high_days_value') or 1
        try:
            hd = int(hd) >> 16  # 高16位=连板数
        except Exception:
            hd = 1
        for th in themes(r.get('reason_type')):
            rows.append((pd.Timestamp(f'{d[:4]}-{d[4:6]}-{d[6:]}'), th, r['code'], hd))

T = pd.DataFrame(rows, columns=['date', 'theme', 'code', 'lb'])
days = np.sort(T.date.unique())
day_str = {d: pd.Timestamp(d).strftime('%Y%m%d') for d in days}
day_idx = {d: i for i, d in enumerate(days)}

cnt = T.groupby(['date', 'theme']).code.nunique().unstack(fill_value=0).reindex(days, fill_value=0)
lb2 = T[T.lb >= 2].groupby(['date', 'theme']).code.nunique().unstack(fill_value=0).reindex(index=days, columns=cnt.columns, fill_value=0)
rk = cnt.rank(axis=1, ascending=False, method='min')

print(f'[1] 交易日 {len(days)} 天 ({pd.Timestamp(days[0]).date()} ~ {pd.Timestamp(days[-1]).date()}), '
      f'题材标签 {cnt.shape[1]} 个, 涨停行 {len(T)} 条(code可重复题材)')


# ============================================================
# 3. 确认规则 —— 分两类, 严格分开归因
#    (a) base_confirm = 字面规则(Buwen定): T(-1与T两天或仅T)涨停只数都排
#        全市场前K, 且都不少于M只。不含 lb2/fresh。
#    (b) full_impl_confirm = theme.py 脚本当前实现: base(两日版) + lb2>=1
#        (T日该题材至少1只两板以上) + fresh(T-1前5个交易日该题材未曾单
#        日达标)。lb2/fresh 两个过滤器系前一个session写 theme.py 时自加,
#        不是 Buwen 原话里的文字, 下面明确标注、分开统计。
# ============================================================
def base_confirm(K=3, M=5, two_day=True):
    recs = []
    start = 1 if two_day else 0
    for i in range(start, len(days)):
        t = days[i]
        cond = (rk.loc[t] <= K) & (cnt.loc[t] >= M)
        if two_day:
            t1 = days[i - 1]
            cond = cond & (rk.loc[t1] <= K) & (cnt.loc[t1] >= M)
        for th in cond[cond].index:
            rec = {'date': t, 'theme': th, 'c_t': int(cnt.loc[t, th]), 'rank_t': int(rk.loc[t, th])}
            if two_day:
                rec['c_t1'] = int(cnt.loc[t1, th]); rec['rank_t1'] = int(rk.loc[t1, th])
            recs.append(rec)
    return pd.DataFrame(recs)


def full_impl_confirm(K=3, M=5, fresh_window=5):
    """逐字复刻 theme.py 的 run(K,M,fresh=True) 口径。"""
    recs = []
    for i in range(6, len(days)):
        t, t1 = days[i], days[i - 1]
        cond = (rk.loc[t] <= K) & (rk.loc[t1] <= K) & (cnt.loc[t] >= M) & (cnt.loc[t1] >= M) & (lb2.loc[t] >= 1)
        lo, hi = i - 1 - fresh_window, i - 1
        prior = (rk.iloc[lo:hi] <= K) & (cnt.iloc[lo:hi] >= M)
        cond = cond & ~prior.any()
        for th in cond[cond].index:
            recs.append({'date': t, 'theme': th, 'c_t': int(cnt.loc[t, th]), 'c_t1': int(cnt.loc[t1, th])})
    return pd.DataFrame(recs)


BASE_K, BASE_M = 3, 5  # 字面规则默认参数: 排前三, 不少于5只
sig_base = base_confirm(BASE_K, BASE_M, two_day=True)
sig_full = full_impl_confirm(BASE_K, BASE_M)

base_by_day = sig_base.groupby('date')['theme'].apply(list).to_dict() if len(sig_base) else {}
full_by_day = sig_full.groupby('date')['theme'].apply(list).to_dict() if len(sig_full) else {}

print(f'[2] 字面规则(K={BASE_K},M={BASE_M},两日版) 全样本确认事件 {len(sig_base)} 条, '
      f'确认天数 {len(base_by_day)} 天 / {len(days)} 天 ({len(base_by_day)/len(days)*100:.1f}%)')
print(f'    当前脚本实现(+lb2>=1,+fresh5日) 全样本确认事件 {len(sig_full)} 条, '
      f'确认天数 {len(full_by_day)} 天 / {len(days)} 天 ({len(full_by_day)/len(days)*100:.1f}%)')


# ============================================================
# 4. daily_confirm.csv —— 覆盖全样本 2025-09-24~2026-10-19, 每天一行
# ============================================================
daily_rows = []
for i, t in enumerate(days):
    ds = day_str[t]
    top = cnt.loc[t].sort_values(ascending=False)
    top = top[top > 0]
    top3 = list(top.head(3).items())
    while len(top3) < 3:
        top3.append((None, 0))
    rec = {
        'date': pd.Timestamp(t).strftime('%Y-%m-%d'),
        'total_zt': daily_total_zt.get(ds, None),
        'top1_theme': top3[0][0], 'top1_cnt': int(top3[0][1]),
        'top2_theme': top3[1][0], 'top2_cnt': int(top3[1][1]),
        'top3_theme': top3[2][0], 'top3_cnt': int(top3[2][1]),
        'confirmed_base': 1 if t in base_by_day else 0,
        'themes_base': ';'.join(base_by_day.get(t, [])),
        'confirmed_full_impl': 1 if t in full_by_day else 0,
        'themes_full_impl': ';'.join(full_by_day.get(t, [])),
    }
    daily_rows.append(rec)
daily_df = pd.DataFrame(daily_rows)
daily_df.to_csv(f'{OUT}/daily_confirm.csv', index=False, encoding='utf-8-sig')
print(f'[3] daily_confirm.csv 写入 {len(daily_df)} 行')

# 月度汇总(字面规则 + 当前实现 两套口径对照)
daily_df['month'] = daily_df['date'].str[:7]
def month_theme_set(sub, col):
    s = set()
    for v in sub[col]:
        if v:
            s.update(v.split(';'))
    return len(s)

monthly = []
for m, sub in daily_df.groupby('month'):
    monthly.append({
        'month': m,
        'trading_days': len(sub),
        'confirm_days_base': int(sub['confirmed_base'].sum()),
        'themes_base_distinct': month_theme_set(sub, 'themes_base'),
        'confirm_days_full_impl': int(sub['confirmed_full_impl'].sum()),
        'themes_full_impl_distinct': month_theme_set(sub, 'themes_full_impl'),
    })
monthly_df = pd.DataFrame(monthly)
monthly_df.to_csv(f'{OUT}/monthly_confirm.csv', index=False, encoding='utf-8-sig')
print(f'[4] monthly_confirm.csv 写入 {len(monthly_df)} 个月')
print(monthly_df.to_string(index=False))


# ============================================================
# 5. 与实际买入+台账交叉对照 (2026-09-17 ~ 2026-10-19)
# ============================================================
pf = json.load(open(PORTFOLIO))
trades = [t for t in pf['trade_log']
          if t.get('account') == 'a_share' and t.get('action') == 'buy' and t.get('date', '') >= '2026-09-17']
print(f'\n[5] portfolio_state.json: 09-17起 a_share 买入 {len(trades)} 笔')
for t in trades:
    print(f"    {t['date']} {t.get('ticker')} {t.get('name')} reason前80字: {t.get('reason','')[:80]}")

window = daily_df[(daily_df['date'] >= '2026-09-17') & (daily_df['date'] <= '2026-10-19')].copy()
buy_dates = sorted(set(t['date'] for t in trades))
window['bought_s1'] = window['date'].isin(buy_dates).astype(int)
window.to_csv(f'{OUT}/window_09-17_10-19.csv', index=False, encoding='utf-8-sig')

confirmed_no_buy = window[(window['confirmed_base'] == 1) & (window['bought_s1'] == 0)]
buy_no_confirm = window[(window['bought_s1'] == 1) & (window['confirmed_base'] == 0)]
print(f'\n[5a] 09-17~10-19窗口 {len(window)} 个交易日, 字面规则确认 {int(window.confirmed_base.sum())} 天, 实际买入 {len(buy_dates)} 天')
print(f'[5b] 规则确认但当天未买(策略一)的交易日 n={len(confirmed_no_buy)}:')
for _, r in confirmed_no_buy.iterrows():
    print(f"     {r['date']} 确认题材={r['themes_base']} top1={r['top1_theme']}({r['top1_cnt']}) top2={r['top2_theme']}({r['top2_cnt']}) top3={r['top3_theme']}({r['top3_cnt']})")
print(f'[5c] 规则未确认但当天买入(策略一)的交易日 n={len(buy_no_confirm)}:')
for _, r in buy_no_confirm.iterrows():
    print(f"     {r['date']} top1={r['top1_theme']}({r['top1_cnt']}) top2={r['top2_theme']}({r['top2_cnt']}) top3={r['top3_theme']}({r['top3_cnt']})")


# ============================================================
# 6. 参数敏感性 —— K x M x 单日/两日版, 样本内/外分开
#    只用字面规则(无 lb2/fresh); 买T+1开盘, 持4个交易日, 粗口径收益/胜率
# ============================================================
IN_START, IN_END = '2025-09-01', '2026-03-31'
OUT_START, OUT_END = '2026-04-01', '2026-10-19'

# 候选 (date,theme) 对: 任何被测K(<=5)/M(>=3)组合下"单日"可能够格的全集
cand = []
for i, t in enumerate(days):
    r = rk.loc[t]; c = cnt.loc[t]
    ok = (r <= 5) & (c >= 3)
    for th in ok[ok].index:
        cand.append((i, t, th, int(c[th]), int(r[th])))
cand_df = pd.DataFrame(cand, columns=['i', 'date', 'theme', 'c', 'rank'])
print(f'\n[6] 候选(date,theme)对(cnt>=3且rank<=5, 任一测试组合可能用到) n={len(cand_df)}')

# ---- 6a. 用本地价格库算每个候选对的"T+1开盘买, 持4交易日"逐股收益 ----
need_codes = sorted(T[T.set_index(['date','theme']).index.isin(
    list(zip(cand_df.date, cand_df.theme)))].code.unique()) if len(cand_df) else []
# 简化且稳健: 直接用候选(date,theme)对去 T 里查成员股(不依赖上面的index构造,下面重做一次,更直接)
pair2codes = T.groupby(['date', 'theme'])['code'].apply(lambda s: sorted(set(s))).to_dict()

all_codes = sorted(set(c for (_, th), codes in pair2codes.items() for c in codes
                        if (th,) and True))  # 占位, 下面直接用 cand_df 限定的pair取codes
needed_pairs = set(zip(cand_df['date'], cand_df['theme']))
needed_codes = sorted(set(c for p in needed_pairs for c in pair2codes.get(p, [])))
print(f'    涉及股票 {len(needed_codes)} 只, 读价格库(pyarrow过滤 date区间, 非整表读)')


def to_full_ticker(code):
    """涨停池 code 是裸6位数字, 价格库 ticker 带交易所后缀(600825.SH/000001.SZ/920641.BJ)。"""
    if code[:1] == '6':
        return code + '.SH'
    if code[:1] in ('4', '8') or code[:2] == '92':
        return code + '.BJ'
    return code + '.SZ'  # 0/3 开头


code2full = {c: to_full_ticker(c) for c in needed_codes}
full2code = {v: k for k, v in code2full.items()}
needed_full = sorted(code2full.values())

import pyarrow.parquet as pq
price_tbl = pq.read_table(
    PRICE_DB,
    filters=[('date', '>=', pd.Timestamp('2025-08-01')), ('date', '<=', pd.Timestamp('2026-10-19'))],
    columns=['date', 'ticker', 'open', 'high', 'low', 'close', 'adj_close', 'volume'],
)
price_df = price_tbl.to_pandas()
price_df = price_df[price_df['ticker'].isin(needed_full)].copy()
price_df['code'] = price_df['ticker'].map(full2code)
price_df.sort_values(['code', 'date'], inplace=True)
price_by_code = {code: g.reset_index(drop=True) for code, g in price_df.groupby('code')}
print(f'    价格库过滤后 {len(price_df)} 行, 覆盖 {price_df.code.nunique()} 只股票(需要{len(needed_codes)}只, '
      f'缺失{len(set(needed_codes)-set(price_df.code.unique()))}只)')

ZT_PCT = {}  # ticker prefix -> 涨跌停幅度(简化: 不单独处理ST, 已在summary.md标注caveat)
def limit_pct(code):
    if code[:1] in ('4', '8') or code[:2] == '92':
        return 0.30
    if code[:2] in ('30', '68') or code[:3] == '301':
        return 0.20
    return 0.10


def trade_return(code, sig_date):
    """code 在 sig_date(T) 当天涨停(属于某确认题材); 在 T+1 开盘买, 持4个交易日(T+4收盘卖)。
    返回 (ret_pct, flag) flag in {'ok','one_board_lock','no_data','suspended'}"""
    g = price_by_code.get(code)
    if g is None or len(g) == 0:
        return None, 'no_data'
    dates = g['date'].values
    pos = np.searchsorted(dates, np.datetime64(sig_date))
    if pos >= len(dates) or dates[pos] != np.datetime64(sig_date):
        return None, 'no_data'
    if pos + 4 >= len(g):
        return None, 'no_data'  # 不够4个交易日后的数据(价格库覆盖到10-19的尾部样本)
    row_t = g.iloc[pos]
    row_t1 = g.iloc[pos + 1]
    row_t4 = g.iloc[pos + 4]
    # T+1 是否为该股的"下一个自然交易日"(非停牌跳空) —— 用全市场交易日历核验
    gi = day_idx.get(np.datetime64(sig_date))
    if gi is None or gi + 1 >= len(days) or gi + 4 >= len(days):
        return None, 'no_data'
    expect_t1 = days[gi + 1]
    expect_t4 = days[gi + 4]
    if row_t1['date'] != expect_t1 or row_t4['date'] != expect_t4:
        return None, 'suspended'  # 该股在T+1或T+4前后停牌, 价格序列与大盘交易日错位
    # 一字板判定: T+1当天 open=high=low=涨停价 (涨停价按T收盘不复权close计算, 四位小数容差同题目公式)
    lp = round(row_t['close'] * (1 + limit_pct(code)), 2)
    is_one_word = (row_t1['open'] == row_t1['high'] == row_t1['low']) and (row_t1['close'] >= lp - 0.005)
    if is_one_word:
        return None, 'one_board_lock'
    if row_t1['close'] == 0 or pd.isna(row_t1['open']) or pd.isna(row_t4['adj_close']):
        return None, 'no_data'
    # 多日收益用 adj_close; T+1开盘价换算到与adj_close同一复权基准(用T+1当天 adj_close/close 的比例)
    if row_t1['close'] == 0 or pd.isna(row_t1['close']):
        return None, 'no_data'
    factor_t1 = row_t1['adj_close'] / row_t1['close']
    adj_open_t1 = row_t1['open'] * factor_t1
    if adj_open_t1 <= 0:
        return None, 'no_data'
    ret = row_t4['adj_close'] / adj_open_t1 - 1.0
    return ret, 'ok'


# 逐候选对计算逐股收益(缓存, 跨K/M复用)
pair_returns = {}
pair_flags = {}
for (d, th), codes in pair2codes.items():
    if (d, th) not in needed_pairs:
        continue
    rets, flags = [], []
    for code in codes:
        r, fl = trade_return(code, d)
        flags.append(fl)
        if r is not None:
            rets.append(r)
    pair_returns[(d, th)] = rets
    pair_flags[(d, th)] = flags

n_ok = sum(len(v) for v in pair_returns.values())
n_excl = sum(len(v) for v in pair_flags.values()) - n_ok
print(f'    逐股收益样本: 可成交 {n_ok} 笔, 剔除(一字板/停牌/数据不足) {n_excl} 笔')


def sample_tag(date):
    s = pd.Timestamp(date).strftime('%Y-%m-%d')
    if IN_START <= s <= IN_END:
        return 'in'
    if OUT_START <= s <= OUT_END:
        return 'out'
    return None


sens_rows = []
for K in (2, 3, 5):
    for M in (3, 4, 5, 6):
        for two_day in (True, False):
            ver = '两日版' if two_day else '单日版'
            for sample in ('in', 'out'):
                lo, hi = (IN_START, IN_END) if sample == 'in' else (OUT_START, OUT_END)
                # 该参数组合在该样本段内的信号(date,theme)对
                sub = cand_df[(cand_df['rank'] <= K) & (cand_df['c'] >= M)]
                sig_pairs = []
                for _, row in sub.iterrows():
                    i, t, th = row['i'], row['date'], row['theme']
                    ds = pd.Timestamp(t).strftime('%Y-%m-%d')
                    if not (lo <= ds <= hi):
                        continue
                    if two_day:
                        if i - 1 < 0:
                            continue
                        t1 = days[i - 1]
                        if rk.loc[t1, th] <= K and cnt.loc[t1, th] >= M:
                            sig_pairs.append((t, th))
                    else:
                        sig_pairs.append((t, th))
                sig_pairs = sorted(set(sig_pairs))
                n_signal = len(sig_pairs)
                months = 7  # 两段样本均为7个日历月(含两端各一个不完整月, summary.md注明)
                rets = []
                for p in sig_pairs:
                    rets.extend(pair_returns.get(p, []))
                n_trade = len(rets)
                avg_ret = float(np.mean(rets)) * 100 if n_trade else None
                win_rate = float(np.mean([1 if x > 0 else 0 for x in rets])) * 100 if n_trade else None
                sens_rows.append({
                    'K': K, 'M': M, 'version': ver, 'sample': '样本内2025-09~2026-03' if sample == 'in' else '样本外2026-04~2026-10',
                    'signal_days_theme_pairs': n_signal,
                    'months': months,
                    'signals_per_month': round(n_signal / months, 2),
                    'trade_n': n_trade,
                    'avg_return_pct_4d': round(avg_ret, 2) if avg_ret is not None else None,
                    'win_rate_pct': round(win_rate, 1) if win_rate is not None else None,
                })

sens_df = pd.DataFrame(sens_rows)
sens_df.to_csv(f'{OUT}/sensitivity.csv', index=False, encoding='utf-8-sig')
print(f'\n[7] sensitivity.csv 写入 {len(sens_df)} 行 (K x M x 版本 x 样本段)')
print(sens_df.to_string(index=False))


# ============================================================
# 7. 题材并组口径的影响 —— 机器人家族为例
# ============================================================
robot_raw = sorted(set(th for th in cnt.columns if ('机器人' in th) or ('具身' in th)))
print(f'\n[8] 当前未并组的机器人系标签 {len(robot_raw)} 个: {robot_raw[:15]} ...(仅显示前15)')

def confirm_days_with_merge(K, M, merge_labels, merged_name='机器人(并组后)'):
    c2 = cnt.copy()
    if merge_labels:
        present = [l for l in merge_labels if l in c2.columns]
        merged = c2[present].sum(axis=1)
        c2 = c2.drop(columns=present)
        c2[merged_name] = merged
    r2 = c2.rank(axis=1, ascending=False, method='min')
    confirmed_days = set()
    for i in range(1, len(days)):
        t, t1 = days[i], days[i - 1]
        cond = (r2.loc[t] <= K) & (c2.loc[t] >= M) & (r2.loc[t1] <= K) & (c2.loc[t1] >= M)
        if cond.any():
            confirmed_days.add(t)
    return confirmed_days

base_days_set = set(base_by_day.keys())
merge_robot_only = [l for l in robot_raw if '具身' not in l]
merge_days_robot = confirm_days_with_merge(BASE_K, BASE_M, merge_robot_only)
merge_days_robot_plus = confirm_days_with_merge(BASE_K, BASE_M, robot_raw)

new_days_robot = merge_days_robot - base_days_set
new_days_robot_plus = merge_days_robot_plus - base_days_set
print(f'[9] 并组影响(K={BASE_K},M={BASE_M},两日版, 全样本{len(days)}天):')
print(f'    现状(不并组)确认天数 = {len(base_days_set)}')
print(f'    仅并"机器人/人形机器人/工业机器人/机器人概念"等{len(merge_robot_only)}个标签 → 确认天数 = {len(merge_days_robot)}, '
      f'新增 {len(new_days_robot)} 天: {sorted(pd.Timestamp(d).strftime("%Y-%m-%d") for d in new_days_robot)}')
print(f'    连"具身智能"系也并入(共{len(robot_raw)}个标签) → 确认天数 = {len(merge_days_robot_plus)}, '
      f'新增 {len(new_days_robot_plus)} 天: {sorted(pd.Timestamp(d).strftime("%Y-%m-%d") for d in new_days_robot_plus)}')

# 机器人家族历史峰值(并组后)供佐证
c2 = cnt.copy()
present = [l for l in merge_robot_only if l in c2.columns]
robot_merged_series = c2[present].sum(axis=1)
top_robot_days = robot_merged_series.sort_values(ascending=False).head(8)
print('[9b] 机器人家族(并组后)历史涨停只数最高的8天:')
for d, v in top_robot_days.items():
    print(f'     {pd.Timestamp(d).date()}  {int(v)}只')


# ============================================================
# 8. 单日达标但次日未能延续("夭折")统计 —— 量化两日持续性门槛的结构性代价
# ============================================================
single_qual = (rk <= BASE_K) & (cnt >= BASE_M)
single_days_count = int(single_qual.sum().sum())
confirmed_pairs_count = len(sig_base)
print(f'\n[10] 字面规则(K={BASE_K},M={BASE_M})下: 单日达标(题材,日)事件共 {single_qual.sum().sum()} 次; '
      f'其中次日仍达标从而确认的只有 {confirmed_pairs_count} 次, 延续率 {confirmed_pairs_count/single_days_count*100:.1f}%'
      if single_days_count else '[10] 无单日达标事件')

print('\n[DONE] script.py 执行完毕, 产出见', OUT)
