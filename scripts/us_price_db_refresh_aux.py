#!/usr/bin/env python3
"""刷新 us_price_db 的三个辅助子库: sectors(89 板块ETF) / commodities(43 期货) / macro(86 FRED 宏观)。

⛔为什么单独有这个脚本: 2026-09-16 体检发现这三个子库**从 09-09 建库那天起就没接过任何增量**,
  sectors 停在 09-08、commodities 与 macro 停在 09-09。个股 prices/ 每天更新、benchmarks 09-16 接上了,
  只有这三个没人管。板块对照和宏观读数都会用到它们, 落后 5 到 6 个交易日而无人知晓, 是因为
  从来没有任何一处会为此报错——又一次"故障降级成语义合法的旧值"。

⛔本脚本落地当天从主库事故里学到的三条纪律(见 memory/feedback_fault_must_shout 第六例):
  1. 丢弃空值行: 数据源在收盘后数小时给的当日 bar 只有 open/high/low/volume, close 为空。
     不过滤就会落盘, 还因日期最大而成为"末日"。
  2. 起点按最后一个**有效值**算, 并往回 lookback 天重拉: 只拉"末日之后"等于假定已落盘的行永远正确,
     而数据源事后改口是常态(拆股还原、幽灵bar撤回、半截bar补全)。
  3. 输出必须带值、断言必须非零退出: 只打印"末日 09-15"时, 空行和真有价的长得一模一样。

⛔两个不能照搬 benchmarks 的地方(照搬必然误报):
  · macro 是 FRED, 日频/周频/月频混在一个目录里, 新鲜度必须**按 catalog 的 freq 列分档判**。
  · commodities 是期货, 交易时段比现货长, 末日可以比 SPY 晚一天, 不能用"落后 SPY"当判据。

符号映射取自 catalog.csv(权威, 不靠猜): source 含空格则取空格后那截(如 "yfinance 6A=F" -> 6A=F),
否则 symbol 即 series。已对 89+44+86 条全量验证, 无例外。

用法:
    python3 us_price_db_refresh_aux.py                 # 刷新三个子库
    python3 us_price_db_refresh_aux.py --only sectors  # 只刷一个
    python3 us_price_db_refresh_aux.py --lookback 20   # 加大回看(修历史污染时用)
    python3 us_price_db_refresh_aux.py --dry-run       # 只报告该拉什么, 不写盘

退出码: 0=全部干净 / 1=有序列失败 / 2=整体失败(熔断) / 4=新鲜度或空值断言不通过
"""
import warnings, sys, os, time, argparse, json
warnings.filterwarnings('ignore')
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB   = os.path.join(ROOT, 'data', 'us_price_db')
CAT  = os.path.join(DB, 'catalog.csv')

ap = argparse.ArgumentParser()
ap.add_argument('--only', choices=['sectors', 'commodities', 'macro'], help='只刷这一个子库')
ap.add_argument('--lookback', type=int, default=7, help='从最后一个有效值往回多少天重拉, 用来覆盖数据源事后的修正')
ap.add_argument('--dry-run', action='store_true', help='只报告不写盘')
args = ap.parse_args()

CATEGORY = {'sectors': 'sector_etf', 'commodities': 'commodity', 'macro': 'macro'}
# 新鲜度容忍(日历天)。⛔月频序列本来就可能一个月才更新一次, 用统一阈值判它必然误报。
FRESH_BY_FREQ = {'D': 6, 'W': 12, 'M': 45, 'Q': 130, 'A': 400, 'S': 250}

cat = pd.read_csv(CAT)


def symbol_of(row):
    s = str(row['source'])
    return s.split(' ', 1)[1].strip() if ' ' in s else str(row['series'])


def fetch_yf(sym, start):
    import yfinance as yf
    s = yf.Ticker(sym).history(start=start, interval='1d')
    if s.empty:
        return None
    s = s.rename(columns={'Adj Close': 'adj_close'})
    s.columns = [c.lower().replace(' ', '_') for c in s.columns]
    if 'adj_close' not in s.columns:
        s['adj_close'] = s['close']
    s = s[['open', 'high', 'low', 'close', 'adj_close', 'volume']]
    s = s[s['close'].notna()]                      # 纪律1
    s.index = pd.to_datetime(s.index).tz_localize(None)
    s.index.name = 'date'
    return s if len(s) else None


_FRED_KEY = None
def fred_key():
    global _FRED_KEY
    if _FRED_KEY is None:
        _FRED_KEY = os.environ.get('FRED_API_KEY', '')
        if not _FRED_KEY:
            p = os.path.join(ROOT, '.env')
            if os.path.exists(p):
                for line in open(p):
                    if line.strip().startswith('FRED_API_KEY'):
                        _FRED_KEY = line.split('=', 1)[1].strip().strip('"').strip("'")
    return _FRED_KEY


def fetch_fred(series_id, start):
    """优先官方 API(带 key, 无限流), 失败回落公共 CSV 端点。
    ⛔2026-09-16 实测: api 与 fredgraph 两个域名都解析到 198.18.x.x(代理 fake-ip), 但**都是 200**。
      劫持是转发型不是阻断型, 所以不能看见 198.18 就断言拿不到——要以实际返回为准。"""
    import requests, io
    k = fred_key()
    if k:
        try:
            r = requests.get('https://api.stlouisfed.org/fred/series/observations',
                             params={'series_id': series_id, 'api_key': k, 'file_type': 'json',
                                     'observation_start': start}, timeout=25)
            if r.status_code == 200:
                obs = r.json().get('observations', [])
                df = pd.DataFrame([(o['date'], o['value']) for o in obs], columns=['date', 'value'])
                df['value'] = pd.to_numeric(df['value'], errors='coerce')   # FRED 用 "." 表示缺测
                df = df[df['value'].notna()]                                 # 纪律1
                if len(df):
                    df['date'] = pd.to_datetime(df['date'])
                    return df.set_index('date')[['value']]
                return None
        except Exception as e:
            print(f'    api 失败({type(e).__name__}), 回落 csv', flush=True)
    try:
        r = requests.get(f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}', timeout=25)
        if r.status_code != 200:
            return None
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = ['date', 'value']
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        df = df[df['value'].notna()]
        if not len(df):
            return None
        df['date'] = pd.to_datetime(df['date'])
        return df.set_index('date')[['value']][lambda d: d.index >= pd.Timestamp(start)]
    except Exception:
        return None


def refresh(subdir):
    """返回 (done, failed, stale) 三个清单。done 元素 = (series, 末日, 行数, 末值, freq)"""
    rows = cat[cat.category == CATEGORY[subdir]]
    outdir = os.path.join(DB, subdir)
    done, failed, stale, retired = [], [], [], []
    synced = set()   # macro 专用: 已确认同步到 FRED 当前最新 observation 的序列
    print(f'\n=== {subdir}: {len(rows)} 条 ===', flush=True)
    for _, r in rows.iterrows():
        series, sym, freq = str(r['series']), symbol_of(r), str(r.get('freq', 'D')).upper()[:1]
        # ⛔已终止的序列(合约停止交易、指标停止发布)跳过拉取与新鲜度断言, 但保留历史文件。
        #   不这么做的后果不是漏报而是**滥报**: LBS=F 随机长度木材期货 2023-05-15 停止交易,
        #   新鲜度断言会判它已过期 1200 多天, 于是每天报一次 exit 4。
        #   一个永远会响、永远修不好的告警, 最终结果是让人开始忽略所有告警 —— 这比不报更危险。
        #   ⛔"已终止"必须是人工查证后写进 catalog 的结论, 不许脚本看到拉不到数据就自己标,
        #     否则真故障(网络断、凭据过期、符号写错)会被自动洗成"它退市了"。
        if str(r.get('status', '')).strip().lower() == 'retired':
            retired.append((series, str(r.get('last', '')), str(r.get('name', ''))))
            continue
        fp = os.path.join(outdir, f'{series}.parquet')
        old, last = None, None
        if os.path.exists(fp):
            old = pd.read_parquet(fp)
            old.index = pd.to_datetime(old.index)
            if getattr(old.index, 'tz', None) is not None:
                old.index = old.index.tz_localize(None)
            vcol = 'value' if 'value' in old.columns else 'close'
            ov = old[old[vcol].notna()]
            last = ov.index.max() if len(ov) else None
        # 纪律2: 从最后一个有效值往回 lookback 天, 不是只拉末日之后
        start = (last - pd.Timedelta(days=args.lookback)).strftime('%Y-%m-%d') if last is not None else '1990-01-01'
        try:
            new = fetch_fred(sym, start) if subdir == 'macro' else fetch_yf(sym, start)
            if new is None or not len(new):
                # 取不到新数据时保留旧文件不动, 但要记 stale 而不是当成成功
                if last is not None:
                    done.append((series, str(last.date()), len(old), float(old[('value' if 'value' in old.columns else 'close')].loc[last]), freq))
                else:
                    failed.append((series, '无数据且无旧文件'))
                continue
            merged = new if old is None else pd.concat([old, new])
            merged = merged[~merged.index.duplicated(keep='last')].sort_index()
            if not args.dry_run:
                merged.to_parquet(fp)
            vcol = 'value' if 'value' in merged.columns else 'close'
            # ⛔FRED 序列的新鲜度不能用"离今天几天"判。那衡量的是 FRED 发布得勤不勤, 不是我同步得对不对:
            #   CPI 是月频、GDP 是季频、FYFSGDA188S 是年频, 它们停在两个月前本来就是正常的。
            #   实测: 48 条超容忍告警里 19 条(macro 全部)其实都已经是 FRED 的最新 observation。
            #   照这样接进每日调度, 就是每天报 47 条噪音 —— 而一个天天响的告警等于没有告警。
            #   改用有唯一正确答案的锚点: 我拉回来的末日就是 FRED 当前最新(拉取不设 limit),
            #   合并后末日与它一致 = 已同步到源。对不上才是真问题。
            if subdir == 'macro' and merged.index.max() == new.index.max():
                synced.add(series)
            done.append((series, str(merged.index.max().date()), len(merged), float(merged[vcol].iloc[-1]), freq))
        except Exception as e:
            failed.append((series, f'{type(e).__name__}: {str(e)[:60]}'))
        if subdir == 'macro':
            time.sleep(0.15)
    # ⛔熔断: 整批全失败是系统性故障(网络/凭据/端点), 不是"这些序列恰好都没数据"
    if len(rows) >= 10 and len(failed) == len(rows):
        print(f'⛔⛔ {subdir} 整批 {len(rows)} 条全部失败, 判为系统性故障', flush=True)
        return done, failed, stale
    # 纪律3: 按 freq 分档判新鲜度
    today = pd.Timestamp.today().normalize()
    for series, last, n, px, freq in done:
        # 已确认同步到源最新的 FRED 序列不看日历: 它停在两个月前只说明这个指标是月频, 不说明我落后
        if series in synced:
            continue
        tol = FRESH_BY_FREQ.get(freq, 6)
        if (today - pd.Timestamp(last)).days > tol:
            stale.append((series, last, freq, (today - pd.Timestamp(last)).days, tol))
    if retired:
        # 跳过也要说出来: 静默跳过和"没有这一条"在输出里长得一样
        print(f'  已终止跳过 {len(retired)} 条: {[x[0] for x in retired]}', flush=True)
    return done, failed, stale


subs = [args.only] if args.only else ['sectors', 'commodities', 'macro']
all_done, all_failed, all_stale, blown = [], [], [], []
for sub in subs:
    d, f, s = refresh(sub)
    if len(cat[cat.category == CATEGORY[sub]]) >= 10 and len(f) == len(cat[cat.category == CATEGORY[sub]]):
        blown.append(sub)
    all_done += [(sub,) + x for x in d]
    all_failed += [(sub,) + x for x in f]
    all_stale += [(sub,) + x for x in s]
    if d:
        lasts = sorted(set(x[1] for x in d))
        print(f'  刷新 {len(d)}/{len(cat[cat.category == CATEGORY[sub]])} 条 | 末日 {lasts[0]} ~ {lasts[-1]}', flush=True)
        for series, last, n, px, freq in d[:3]:
            print(f'    {series:14s} 末日 {last} 末值 {px:>12,.3f} 行数 {n} ({freq})', flush=True)
    if f:
        print(f'  ⛔ 失败 {len(f)} 条: {f[:5]}', flush=True)

# 回写 catalog 的 last / n / status
if not args.dry_run and all_done:
    idx = cat.set_index('series')
    for sub, series, last, n, px, freq in all_done:
        if series in idx.index:
            cat.loc[cat.series == series, 'last'] = last
            cat.loc[cat.series == series, 'n'] = n
            cat.loc[cat.series == series, 'status'] = 'ok'
    for sub, series, err in all_failed:
        cat.loc[cat.series == series, 'status'] = 'failed'
    cat.to_csv(CAT, index=False)
    print(f'\ncatalog.csv 已回写 {len(all_done)} 条', flush=True)

print(f'\n汇总: 成功 {len(all_done)} | 失败 {len(all_failed)} | 超新鲜度 {len(all_stale)}', flush=True)
if all_stale:
    print('⛔ 以下序列超出其频率对应的新鲜度容忍:', flush=True)
    for sub, series, last, freq, age, tol in all_stale[:20]:
        print(f'    {sub}/{series:14s} 末日 {last} ({freq}频, 已 {age} 天 > 容忍 {tol} 天)', flush=True)

if blown:
    print(f'⛔⛔ 整体失败熔断: {blown}', flush=True); sys.exit(2)
if all_stale:
    sys.exit(4)
if all_failed:
    sys.exit(1)
sys.exit(0)
