#!/usr/bin/env python3
"""美股长期价格库 拉取/增量更新。库在 data/us_price_db/, 口径见 manifest.json 与 README.html。

用法:
  python3 us_price_db_pull.py                 # 全量重拉 universe.csv 里的全部(约3.4分钟)
  python3 us_price_db_pull.py --incremental   # 每只读末日, 只拉末日+1至今, 追加去重
  python3 us_price_db_pull.py --tickers AAPL MSFT   # 只拉指定几只(全量)

⛔口径: auto_adjust=False 六列全存; close是拆股调整, adj_close是拆股+分红。收益率用adj_close。
⛔幸存者偏差: 名单按09-08市值筛, 退市股不在, yfinance也拉不到退市股(13/13实测为空)。见manifest。
⛔故障不得降级: 异常必须打印; 整批全失败即熔断退出3; 失败清单进manifest.failed。
  (首版 except 吞异常, 480只全失败还在跑, 根因缺pyarrow, 09-09踩过)
"""
import warnings; warnings.filterwarnings('ignore')
import json, time, os, sys, argparse
import pandas as pd, yfinance as yf

HERE=os.path.dirname(os.path.abspath(__file__))
OUT=os.path.join(os.path.dirname(HERE),'data','us_price_db')
PR=os.path.join(OUT,'prices')
os.makedirs(PR,exist_ok=True)

ap=argparse.ArgumentParser()
ap.add_argument('--incremental',action='store_true',help='只拉每只末日之后的, 追加')
ap.add_argument('--tickers',nargs='*',help='只拉这几只')
ap.add_argument('--batch',type=int,default=80)
ap.add_argument('--lookback',type=int,default=7,help='增量模式从最后一个有效收盘日往回多少天重拉, 用来覆盖数据源事后的修正')
ap.add_argument('--start',default='2015-01-01',help='全量模式起点')
ap.add_argument('--merge',action='store_true',help='拉完后重新合并 all_daily.parquet')
args=ap.parse_args()

uni=pd.read_csv(os.path.join(OUT,'universe.csv'))
tk=args.tickers or list(uni.ticker)
END=(pd.Timestamp.today()+pd.Timedelta(days=1)).strftime('%Y-%m-%d')
failed=[]; done_n=0; t0=time.time(); rows_added=0; need_full=[]

def _clean(s):
    s=s.dropna(how='all').rename(columns={'Adj Close':'adj_close'})
    s.columns=[c.lower().replace(' ','_') for c in s.columns]
    s.index.name='date'
    # ⛔2026-09-16: 收盘后数小时内 yfinance 给的当日日线是半截的——open/high/low/volume 都有值, 只有
    #   close 与 adj_close 是 NaN。dropna(how='all') 删不掉它(它不是全空), 于是它被当作正常一行落盘,
    #   还因为日期最大而成了"末日"; 增量下次只拉末日之后, 这行永远等不到重拉, NaN 就永久固化。
    #   实测后果: 09-14 全库 1392 只里 1291 只的 close 是空的。下游取价时它不报错也不叫,
    #   只是静默回退到上一个有值的交易日——research 的 NOW 近3月因此少算 9 个百分点。
    #   ⛔同族: 09-09 修过的 DXY 幽灵 bar(追加式写入 + 只认末日 = 坏行永久化)。见 feedback_fault_must_shout。
    if 'close' in s.columns:
        s=s[s['close'].notna()]
    return s

def pull(batch, tag, start, force_full=False):
    global done_n, rows_added
    for attempt in range(3):
        try:
            # actions=True 才会带回 Dividends 与 Stock Splits 两列, 用来发现"这个窗口里发生过除权"
            df=yf.download(batch,start=start,end=END,auto_adjust=False,progress=False,threads=True,group_by='ticker',actions=True)
            break
        except Exception as e:
            print(f'  [{tag}] 第{attempt+1}次失败 {type(e).__name__}: {str(e)[:80]}',flush=True); time.sleep(15*(attempt+1))
    else:
        failed.extend(batch); return
    for t in batch:
        try:
            # ⛔按列结构判不按batch长度判: 新版yfinance单ticker也返回MultiIndex, 09-09 --tickers AAPL 当场炸
            s=_clean(df[t] if isinstance(df.columns,pd.MultiIndex) else df)
            fp=os.path.join(PR,f'{t}.parquet')
            # ⛔2026-09-16: 一次分红或拆股会重算该标的**全部历史**行的 adj_close, 而增量只覆盖 lookback
            #   窗口内的行, 窗口以外的历史仍带着除权前的旧因子 —— 收盘价全对、日期全对、没有空值,
            #   只有复权因子是过期的, 断言查不出来(它查形状不查口径)。后果是跨越该除权日的长区间收益率系统性偏低。
            #   实证: 09-11 至 09-15 除权的 83 只全部中招, ADP 的 2025-09-15 adj_close 偏高 0.640%, VRSK 偏高 0.268%。
            #   所以窗口内一旦出现除权事件, 这只必须转全量重拉, 不能只补窗口。
            if args.incremental and not force_full and os.path.exists(fp):
                ev=[c for c in ('dividends','stock_splits') if c in s.columns]
                if ev and float(s[ev].fillna(0).abs().to_numpy().sum())>0:
                    need_full.append(t); continue
            s=s[[c for c in ('open','high','low','close','adj_close','volume') if c in s.columns]]
            if args.incremental and not force_full and os.path.exists(fp):
                old=pd.read_parquet(fp)
                if s.empty:
                    continue                                  # 无新数据, 不动旧文件
                s.index=s.index.tz_convert(old.index.tz) if s.index.tz is not None and old.index.tz is not None else s.index
                merged=pd.concat([old,s]); merged=merged[~merged.index.duplicated(keep='last')].sort_index()
                rows_added+=len(merged)-len(old); merged.to_parquet(fp)
            else:
                if s.empty: failed.append(t); continue
                s.to_parquet(fp)
            done_n+=1
        except Exception as e:
            failed.append(t); print(f'  ⛔ {t}: {type(e).__name__}: {str(e)[:120]}',flush=True)
    if len(batch)>=10 and all(t in failed for t in batch):
        print(f'\n⛔⛔ [{tag}] 整批{len(batch)}只全部失败, 判为系统性故障, 熔断退出。',flush=True); sys.exit(3)

if args.incremental:
    # 按每只末日分组, 同末日的一批拉
    groups={}
    for t in tk:
        fp=os.path.join(PR,f'{t}.parquet')
        last=None
        if os.path.exists(fp):
            o=pd.read_parquet(fp)
            # ⛔起点按"最后一个有效收盘日"算, 不按 index.max(): 后者会把半截bar当成已经走完的一天。
            ov=o[o['close'].notna()] if 'close' in o.columns else o
            last=ov.index.max() if len(ov) else None
        # ⛔从末日往回 lookback 天重拉, 不是只拉末日之后。追加式写入最怕数据源事后改口(拆股还原、
        #   幽灵bar撤回、半截bar补全), 只拉之后等于假定已落盘的行永远正确。concat 后 keep='last' 覆盖旧值。
        start=(last-pd.Timedelta(days=args.lookback)).strftime('%Y-%m-%d') if last is not None else args.start
        groups.setdefault(start,[]).append(t)
    print(f'增量模式: {len(tk)}只, 起点分组 {sorted(groups)[:5]}{"..." if len(groups)>5 else ""}',flush=True)
    for start,ts in sorted(groups.items()):
        for i in range(0,len(ts),args.batch):
            pull(ts[i:i+args.batch],f'{start}起 批{i//args.batch+1}',start)
    n_exdiv=0
    if need_full:
        # 除权标的转全量: 只有重拉 1990 至今, 整条 adj_close 才会用上新因子
        todo=list(need_full); need_full.clear(); n_exdiv=len(todo)
        print(f'\n⛔ {n_exdiv} 只在窗口内除权, 转全量重拉(除权会重算全部历史 adj_close): {todo[:12]}{"..." if n_exdiv>12 else ""}',flush=True)
        for i in range(0,len(todo),args.batch):
            pull(todo[i:i+args.batch],f'除权全量 批{i//args.batch+1}','1990-01-01',force_full=True)
        # ⛔转全量的那批若失败, 这些股本轮既没走增量(被 continue 跳过)也没落全量, 当天数据会静默缺失。
        #   所以必须在这里点名, 让它出现在输出里而不是消失。
        lost=[t for t in todo if t in failed]
        if lost:
            print(f'⛔⛔ 其中 {len(lost)} 只全量重拉失败, 本轮既未增量也未全量, 数据停在昨天: {lost}',flush=True)
    print(f'DONE 增量: 处理{done_n}只 新增{rows_added}行 除权转全量{n_exdiv}只 失败{len(failed)} 用时{(time.time()-t0)/60:.1f}分',flush=True)
else:
    print(f'全量模式: {len(tk)}只 {args.start}至{END}',flush=True)
    for i in range(0,len(tk),args.batch):
        b=tk[i:i+args.batch]; pull(b,f'批{i//args.batch+1}/{(len(tk)+args.batch-1)//args.batch}',args.start)
        print(f'批{i//args.batch+1} 完成 | 落盘{done_n} | 失败{len(failed)} | {(time.time()-t0)/60:.1f}分',flush=True); time.sleep(2)
    if failed:
        retry=list(failed); failed=[]
        for t in retry: pull([t],f'重拉{t}',args.start); time.sleep(1)
    print(f'DONE 全量: {done_n}/{len(tk)} 失败{len(failed)} 用时{(time.time()-t0)/60:.1f}分',flush=True)

# 更新 manifest 的拉取时间与失败清单(其他字段保留)
mp=os.path.join(OUT,'manifest.json')
try: m=json.load(open(mp))
except Exception: m={}
m.update(dict(start=args.start if not args.incremental else m.get('start'),last_pull=time.strftime('%Y-%m-%dT%H:%M:%S%z'),last_mode='incremental' if args.incremental else 'full',
              last_failed=failed,last_rows_added=rows_added if args.incremental else None))
json.dump(m,open(mp,'w'),ensure_ascii=False,indent=1)
if args.merge:
    parts=[]
    for f in sorted(os.listdir(PR)):
        if not f.endswith('.parquet'): continue
        d=pd.read_parquet(os.path.join(PR,f)); d['ticker']=f[:-8]; parts.append(d.reset_index())
    big=pd.concat(parts,ignore_index=True); big['date']=pd.to_datetime(big['date']).dt.tz_localize(None)
    big=big[['date','ticker','open','high','low','close','adj_close','volume']].sort_values(['ticker','date'])
    big.to_parquet(os.path.join(OUT,'all_daily.parquet'),index=False)
    # ⛔2026-09-16: 这里原本只打印"末日 xx-xx"就算成功, 而那天全库 93% 的 close 是 NaN。
    #   行数对、末日对、退出码 0 — 输出和"一切正常"长得一模一样, 这正是这个 bug 活了一周的原因。
    #   末日覆盖率和近期空收盘数必须出现在输出里, 不达标就非零退出。
    n_tk=big.ticker.nunique(); last_d=big.date.max()
    cov=big[(big.date==last_d)&big.close.notna()].ticker.nunique()
    nan_recent=int(big[big.date>=last_d-pd.Timedelta(days=30)].close.isna().sum())
    print(f'合并 all_daily.parquet: {len(big):,}行 {n_tk}只 末日{last_d.date()} 覆盖{cov}/{n_tk}({cov/n_tk:.1%}) 近30日空收盘{nan_recent}行',flush=True)
    # ⛔2026-09-17 补: 绝对阈值挡不住"相邻日跳水"。覆盖率 91% 看着还行, 但若前一日是 100%,
    #   那就是一夜之间 126 只标的凭空消失, 而 91% > 90% 照样放行。⛔比变化率远比比绝对值灵敏。
    #   同族病(另一市场的库今日实证): 末根 bar 日期是最新的, 但那一天只剩一小部分标的有数据,
    #   剩下的少数标的把"末日"撑住, 于是新鲜度断言全绿——新鲜度只问最新一天在不在, 不问那天还剩几个人。
    days=sorted(big[big.date>=last_d-pd.Timedelta(days=30)].date.unique())
    drop=None
    if len(days)>=2:
        c=[(d, big[(big.date==d)&big.close.notna()].ticker.nunique()) for d in days]
        for (d0,c0),(d1,c1) in zip(c,c[1:]):
            if c0>0 and c1/c0 < 0.80:
                drop=(str(pd.Timestamp(d0).date()),c0,str(pd.Timestamp(d1).date()),c1,c1/c0-1)
    if drop:
        print(f'⛔⛔ 相邻交易日覆盖跳水: {drop[0]} {drop[1]}只 -> {drop[2]} {drop[3]}只 ({drop[4]*100:+.1f}%), 退出码 4',flush=True); sys.exit(4)
    if cov < n_tk*0.90 or nan_recent:
        print(f'⛔⛔ 末日覆盖不足 90% 或近30日仍有空收盘行 — 库不可用于回测, 退出码 4',flush=True); sys.exit(4)
elif args.incremental:
    print('⛔ 提醒: 逐只文件已更新, all_daily.parquet 未合并, 加 --merge 或手动合并',flush=True)
sys.exit(0 if not failed else 1)
