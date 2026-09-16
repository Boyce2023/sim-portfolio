"""补齐首板统计真正需要的那几百只(新浪, 不复权) — 定向版

⛔ 为什么不再拉全市场 5216 只(2026-09-16 实测教训):
   6分片全市场跑到 1547 只时新浪开始限流: 失败数 0 → 339, 速度 0.45s/只 → 1.09s/只。
   而首板统计根本不需要全市场 —— 只需要:
     ① 涨停池归档 09-08~09-15 出现过的涨停股(223只, 连板判定归档已给)
     ② 归档排除但我的表含的 ST 股(226只)
   去掉已抓到的 1547 只, 只剩 254 只。请求数降一个数量级, 限流风险同步降。

⛔ 温和参数(刚被限流过): 2分片而非6, 每只间隔 0.5s, 失败重试间隔拉长。

用法: python3 fetch_need.py <分片号> <总分片数>
"""
import os
os.environ['NO_PROXY'] = '*'
os.environ['no_proxy'] = '*'

import json, sys, time
import akshare as ak

SHARD, NSHARD = int(sys.argv[1]), int(sys.argv[2])
OUT = '/tmp/dhbr/sina0916'
BEG, END = '20260905', '20260915'
NEED = json.load(open(f'{OUT}/need.json'))
GAP = float(os.environ.get('GAP', '0.5'))
# ⛔2026-09-16: 6分片0.12s间隔 → 新浪在1547只后开始拒绝(失败0→339);
#   2分片0.5s间隔 → 0成功4失败。改单进程 GAP=2.0 再试, 这是同一个源降速,
#   不是第五次换源。放弃条件写死: 失败率>20% 立即停, 不再纠缠。

_p = {'SH': 'sh', 'SZ': 'sz', 'BJ': 'bj'}
fp = f'{OUT}/need_{SHARD}.jsonl'
done = set()
if os.path.exists(fp):
    for ln in open(fp):
        try: done.add(json.loads(ln)['t'])
        except Exception: pass

mine = [t for i, t in enumerate(NEED) if i % NSHARD == SHARD and t not in done]
print(f'[{SHARD}] 本片 {len(mine)} 只 (已抓过 {len(done)} 跳过)', flush=True)

COLS = ['date', 'open', 'high', 'low', 'close', 'volume', 'amount',
        'outstanding_share', 'turnover']
fo = open(fp, 'a'); fe = open(f'{OUT}/needfail_{SHARD}.txt', 'a')
ok = fail = 0
t0 = time.time()
for i, tk in enumerate(mine):
    num, _, sfx = tk.partition('.')
    pre = _p.get(sfx)
    if not pre:
        continue
    got = None
    for attempt in range(4):                      # 限流期多给一次机会
        try:
            df = ak.stock_zh_a_daily(symbol=pre + num, start_date=BEG,
                                     end_date=END, adjust='')
            if df is not None and len(df):
                df = df[[c for c in COLS if c in df.columns]].copy()
                df['date'] = df['date'].astype(str).str[:10]
                got = (list(df.columns), df.values.tolist())
            else:
                got = ([], [])
            break
        except Exception:
            time.sleep(2.0 * (attempt + 1))       # 限流期退避拉长
    if got is None:
        fe.write(tk + '\n'); fe.flush(); fail += 1
    else:
        fo.write(json.dumps({'t': tk, 'c': got[0], 'k': got[1]},
                            ensure_ascii=False, default=str) + '\n')
        fo.flush()
        ok += 1
    if i % 25 == 0:
        print(f'[{SHARD}] {i}/{len(mine)} ok={ok} fail={fail} {time.time()-t0:.0f}s',
              flush=True)
    time.sleep(GAP)                               # ⛔温和节流, GAP 环境变量可调
fo.close(); fe.close()
print(f'[{SHARD}] DONE ok={ok} fail={fail} / {len(mine)}', flush=True)
