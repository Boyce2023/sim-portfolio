#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
偏差猎手独立验证脚本 —— 不信任 script.py 的任何中间产物(daily_confirm.csv等),
从原始 ths/*.json 重新独立实现一遍核心逻辑做交叉验证, 并专查前视/涨停判定/ST/样本重叠等具体偏差点。
只读, 不改任何既有文件。
"""
import json, glob, os, re
import pandas as pd, numpy as np

THEME_DIR = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-10-09-theme'
PRICE_DB = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet'
CAL = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/market_calendar.json'
CUTOFF = '20261019'

print('='*70)
print('[A] 交易日覆盖完整性核查 —— days是否等于真实交易日历(无缺口/无多余)')
print('='*70)
files = sorted(glob.glob(f'{THEME_DIR}/ths/*.json'))
file_dates = sorted(os.path.basename(f)[:8] for f in files if os.path.basename(f)[:8] <= CUTOFF)
print(f'ths/*.json 文件数(<=cutoff): {len(file_dates)}, 范围 {file_dates[0]} ~ {file_dates[-1]}')

cal = json.load(open(CAL))
closed = set(cal['trading_days_by_market']['cn_closed_dates'])
# 用“工作日(周一到周五) 减去 closed” 重建理论交易日历做对照(A股没有国际节假日以外的休市)
start = pd.Timestamp('2025-09-24'); end = pd.Timestamp('2026-10-19')
all_bdays = pd.bdate_range(start, end)
theoretical = sorted(d.strftime('%Y%m%d') for d in all_bdays if d.strftime('%Y-%m-%d') not in closed)
print(f'理论交易日(工作日-休市日历): {len(theoretical)} 天')
missing_in_files = sorted(set(theoretical) - set(file_dates))
extra_in_files = sorted(set(file_dates) - set(theoretical))
print(f'理论有但ths文件缺失的日期: {len(missing_in_files)} {missing_in_files}')
print(f'ths文件有但理论日历没有的日期(可能是节后补班/日历文件不全): {len(extra_in_files)} {extra_in_files}')

# 检查每个文件是否真的有数据(非空), 排除"文件存在但0条"的情况被误当成一个交易日
empty_files = []
daily_total = {}
for f in files:
    d = os.path.basename(f)[:8]
    if d > CUTOFF: continue
    data = json.load(open(f))
    daily_total[d] = len(data)
    if len(data) == 0:
        empty_files.append(d)
print(f'空文件(0条涨停记录,仍会被当成"当天无confirm"但计入分母): {len(empty_files)} {empty_files}')

print()
print('='*70)
print('[B] 独立重算 base_confirm (字面规则K=3,M=5,两日版) —— 不复用script.py代码')
print('='*70)
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
        if not t: continue
        if t in TOK2: out.add(TOK2[t]); continue
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

rows = []
names = {}  # code -> name(抓ST用)
for f in files:
    d = os.path.basename(f)[:8]
    if d > CUTOFF: continue
    for r in json.load(open(f)):
        hd = r.get('high_days_value') or 1
        try: hd = int(hd) >> 16
        except Exception: hd = 1
        names[r['code']] = r.get('name','')
        for th in themes(r.get('reason_type')):
            rows.append((pd.Timestamp(f'{d[:4]}-{d[4:6]}-{d[6:]}'), th, r['code'], hd))
T = pd.DataFrame(rows, columns=['date', 'theme', 'code', 'lb'])
days = np.sort(T.date.unique())
cnt = T.groupby(['date', 'theme']).code.nunique().unstack(fill_value=0).reindex(days, fill_value=0)
rk = cnt.rank(axis=1, ascending=False, method='min')

K, M = 3, 5
confirm_days = set()
event_count = 0
for i in range(1, len(days)):
    t, t1 = days[i], days[i-1]
    cond = (rk.loc[t] <= K) & (cnt.loc[t] >= M) & (rk.loc[t1] <= K) & (cnt.loc[t1] >= M)
    n = int(cond.sum())
    if n > 0:
        confirm_days.add(t)
        event_count += n
print(f'[独立重算] 全样本 {len(days)} 天, base_confirm(K=3,M=5,两日版) 确认天数={len(confirm_days)} ({len(confirm_days)/len(days)*100:.1f}%), 确认事件={event_count}')
print(f'[对照脚本声称] 确认天数=147(57.9%), 确认事件=209  ->  {"一致" if len(confirm_days)==147 and event_count==209 else "不一致,见下方差异分析"}')

print()
print('='*70)
print('[C] 单日达标事件数与两日延续率独立复算 (claim: 564次单日达标, 209次延续, 37.1%)')
print('='*70)
single_qual = (rk <= K) & (cnt >= M)
single_count = int(single_qual.sum().sum())
print(f'[独立重算] 单日达标(题材,日)事件 = {single_count}; 两日确认事件 = {event_count}; 延续率 = {event_count/single_count*100:.1f}%')

print()
print('='*70)
print('[D] 题材并组口径的前视问题 —— 量化哪些确认日仅靠10-14/10-16才加入的标签撑起')
print('='*70)
PATCH_1014 = {'冰雪', '染料', 'CPO光通信'}  # 2026-10-14 加入
PATCH_1016 = {'低空经济'}                    # 2026-10-16 加入(飞行汽车并入)
tainted_days = []
for i in range(1, len(days)):
    t, t1 = days[i], days[i-1]
    cond = (rk.loc[t] <= K) & (cnt.loc[t] >= M) & (rk.loc[t1] <= K) & (cnt.loc[t1] >= M)
    confirmed_themes = list(cond[cond].index)
    if not confirmed_themes:
        continue
    ds = pd.Timestamp(t).strftime('%Y-%m-%d')
    only_patched = all(
        (th in PATCH_1014 and ds < '2026-10-14') or (th in PATCH_1016 and ds < '2026-10-16')
        for th in confirmed_themes
    )
    any_patched_pretimestamp = any(
        (th in PATCH_1014 and ds < '2026-10-14') or (th in PATCH_1016 and ds < '2026-10-16')
        for th in confirmed_themes
    )
    if any_patched_pretimestamp:
        tainted_days.append((ds, confirmed_themes, only_patched))
print(f'受theme.py后补并组影响的确认日(该日至少一个确认主题是用10-14/10-16才加入字典且日期早于补丁日): n={len(tainted_days)}')
for ds, ths_, only in tainted_days:
    print(f'   {ds}  confirmed_themes={ths_}  是否该日仅靠被补丁主题撑起confirmed(若去掉即不再是确认日)={only}')
would_still_confirm_without_patch = sum(1 for _,_,only in tainted_days if not only)
would_flip_to_unconfirmed = sum(1 for _,_,only in tainted_days if only)
print(f'若剔除这些前视标签: {would_flip_to_unconfirmed} 天会从"确认"变"未确认"(影响147的分母), '
      f'另 {would_still_confirm_without_patch} 天靠同日其他主题仍确认(147不变,只影响209的事件数)')
print(f'剔除后修正值: 确认天数 = {len(confirm_days) - would_flip_to_unconfirmed} / {len(days)} '
      f'= {(len(confirm_days)-would_flip_to_unconfirmed)/len(days)*100:.1f}%  (原147/254=57.9%)')
print(f'剔除后修正值: 确认事件 = {event_count - len(tainted_days)}  (原209)')

print()
print('='*70)
print('[E] ST股票 07-06前5%涨跌停误判为10%的敞口量化')
print('='*70)
st_codes_main = sorted(set(c for c, nm in names.items() if 'ST' in nm.upper() and c[:1] in ('0','6') and c[:2] not in ('30',) and c[:1] not in ('4','8')))
print(f'样本涉及的主板ST代码(名称含ST, 0/6开头非创业板非北交所): {len(st_codes_main)} 个 {st_codes_main[:20]}')
# 这些code在07-06前是否出现在任何确认事件涉及的候选对里
cutoff_5pct = pd.Timestamp('2026-07-06')
st_rows_before = T[(T.code.isin(st_codes_main)) & (T.date < cutoff_5pct)]
print(f'这些ST代码在07-06前出现在涨停池行数: {len(st_rows_before)} (涉及{st_rows_before.code.nunique()}只, {st_rows_before.date.nunique()}天)')
st_dates_before = sorted(st_rows_before.date.unique())
st_themes_before = st_rows_before.theme.unique() if len(st_rows_before) else []
print(f'涉及主题: {list(st_themes_before)[:10]}')

print()
print('='*70)
print('[F] 样本重叠 —— sensitivity收益计算中同一(日期,代码)被不同主题重复计入的程度')
print('='*70)
# 复刻script.py 6a节的候选对定义, 查重复
cand_pairs = set()
for i, t in enumerate(days):
    r = rk.loc[t]; c = cnt.loc[t]
    ok = (r <= 5) & (c >= 3)
    for th in ok[ok].index:
        cand_pairs.add((t, th))
pair2codes = T.groupby(['date', 'theme'])['code'].apply(lambda s: sorted(set(s))).to_dict()
code_date_theme_count = {}
for (d, th) in cand_pairs:
    for code in pair2codes.get((d, th), []):
        key = (d, code)
        code_date_theme_count[key] = code_date_theme_count.get(key, 0) + 1
dup = {k: v for k, v in code_date_theme_count.items() if v > 1}
print(f'(日期,代码)候选对里同时属于>=2个候选主题的: {len(dup)} / {len(code_date_theme_count)} 组 '
      f'({len(dup)/len(code_date_theme_count)*100:.1f}%)')
if dup:
    sample = sorted(dup.items(), key=lambda x: -x[1])[:8]
    for (d, code), n in sample:
        print(f'   {pd.Timestamp(d).date()} {code}({names.get(code,"?")}) 出现在 {n} 个候选主题中 -> 该股收益会被重复计入sensitivity的trade_n {n} 次')

print('\n[DONE]')
