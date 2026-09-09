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
ap.add_argument('--start',default='2015-01-01',help='全量模式起点')
ap.add_argument('--merge',action='store_true',help='拉完后重新合并 all_daily.parquet')
args=ap.parse_args()

uni=pd.read_csv(os.path.join(OUT,'universe.csv'))
tk=args.tickers or list(uni.ticker)
END=(pd.Timestamp.today()+pd.Timedelta(days=1)).strftime('%Y-%m-%d')
failed=[]; done_n=0; t0=time.time(); rows_added=0

def _clean(s):
    s=s.dropna(how='all').rename(columns={'Adj Close':'adj_close'})
    s.columns=[c.lower().replace(' ','_') for c in s.columns]
    s.index.name='date'; return s

def pull(batch, tag, start):
    global done_n, rows_added
    for attempt in range(3):
        try:
            df=yf.download(batch,start=start,end=END,auto_adjust=False,progress=False,threads=True,group_by='ticker')
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
            if args.incremental and os.path.exists(fp):
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
        last=pd.read_parquet(fp).index.max() if os.path.exists(fp) else None
        start=(last+pd.Timedelta(days=1)).strftime('%Y-%m-%d') if last is not None else args.start
        groups.setdefault(start,[]).append(t)
    print(f'增量模式: {len(tk)}只, 起点分组 {sorted(groups)[:5]}{"..." if len(groups)>5 else ""}',flush=True)
    for start,ts in sorted(groups.items()):
        for i in range(0,len(ts),args.batch):
            pull(ts[i:i+args.batch],f'{start}起 批{i//args.batch+1}',start)
    print(f'DONE 增量: 处理{done_n}只 新增{rows_added}行 失败{len(failed)} 用时{(time.time()-t0)/60:.1f}分',flush=True)
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
    print(f'合并 all_daily.parquet: {len(big):,}行 {big.ticker.nunique()}只 末日{big.date.max().date()}',flush=True)
elif args.incremental:
    print('⛔ 提醒: 逐只文件已更新, all_daily.parquet 未合并, 加 --merge 或手动合并',flush=True)
sys.exit(0 if not failed else 1)
