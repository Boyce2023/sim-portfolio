"""把 A股日线从 09-08 补到 09-15 (新浪, 不复权) — 这也是当初建库用的源

⛔ 2026-09-16 选源经过(四条路全试过, 别再走回头路):
   腾讯 ifzq.gtimg.cn   → HTTP 501, 走代理绕代理都一样(TUN fake-IP 劫持到 198.18.0.232,
                          应用层 ProxyHandler 绕不掉 TUN); 且只给6字段没有成交额换手率
   iFinD history        → errorcode -4318 本月额度已用完
   东财 push2his/push2  → 首次 NO_PROXY 后 200, 之后一律 RemoteDisconnected(反爬), 3次重试也不过
   东财 push2delay      → 有响应但没有 kline 端点, data 为空
   ⭐新浪 stock_zh_a_daily → 0.66s/只, 且自带 outstanding_share 与 amount, 市值口径最干净
   (memory/reference_cn_hk_price_db.md 写着这个库当初就是新浪建的, 我却先去撞了腾讯和东财)

⛔⛔ 单位量纲(今天上午市值算错100倍就栽在这一条):
   新浪 turnover = 小数比例, 0.292419 就是 29.24%, 不是百分数。
   所以市值一律走 outstanding_share * close, 不用换手率反推。
   已交叉验证: 闽东 09-15  457,951,455 * 16.80 = 76.9亿, 与涨停池归档 76.9亿 一致。

⛔ 进程纪律: 单线程(多线程撞 V8 秒退, 见 feedback_bulk_fetch_process_hygiene) +
   每条 flush + 断点续跑 + 失败单独记录。

用法: python3 fetch_sina.py <分片号> <总分片数>
"""
import os
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

import json, sys, time
import akshare as ak
import pandas as pd

SHARD, NSHARD = int(sys.argv[1]), int(sys.argv[2])
OUT = '/tmp/dhbr/sina0916'
os.makedirs(OUT, exist_ok=True)
BEG, END = '20260905', '20260915'     # 09-16未收盘, 当日bar不完整, 不取
PQ = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet'

univ = sorted(set(pd.read_parquet(PQ, columns=['ticker'])['ticker'].unique()))
_p = {'SH': 'sh', 'SZ': 'sz', 'BJ': 'bj'}

done = set()
fp = f'{OUT}/shard_{SHARD}.jsonl'
if os.path.exists(fp):
    for ln in open(fp):
        try: done.add(json.loads(ln)['t'])
        except Exception: pass
print(f'[{SHARD}] 已抓过 {len(done)} 只, 跳过', flush=True)

mine = [t for i, t in enumerate(univ) if i % NSHARD == SHARD and t not in done]
COLS = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount',
        'outstanding_share', 'turnover']

fo = open(fp, 'a'); fe = open(f'{OUT}/fail_{SHARD}.txt', 'a')
ok = fail = 0
t0 = time.time()
for i, tk in enumerate(mine):
    num, _, sfx = tk.partition('.')
    pre = _p.get(sfx)
    if not pre:
        continue
    got = None
    for attempt in range(3):
        try:
            df = ak.stock_zh_a_daily(symbol=pre + num, start_date=BEG,
                                     end_date=END, adjust='')
            if df is not None and len(df):
                df = df[[c for c in COLS if c in df.columns]].copy()
                df['date'] = df['date'].astype(str).str[:10]
                got = df.values.tolist()
            else:
                got = []
            break
        except Exception:
            time.sleep(0.7 * (attempt + 1))
    if got is None:
        fe.write(tk + '\n'); fe.flush(); fail += 1
    else:
        fo.write(json.dumps({'t': tk, 'c': list(df.columns) if got else [],
                             'k': got}, ensure_ascii=False, default=str) + '\n')
        fo.flush()
        ok += 1
    if i % 50 == 0:
        print(f'[{SHARD}] {i}/{len(mine)} ok={ok} fail={fail} {time.time()-t0:.0f}s',
              flush=True)
fo.close(); fe.close()
print(f'[{SHARD}] DONE ok={ok} fail={fail} / {len(mine)}', flush=True)
