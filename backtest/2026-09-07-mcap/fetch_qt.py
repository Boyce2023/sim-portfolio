"""把 A股日线从 09-08 补到 09-15 (腾讯 ifzq, 不复权)

⛔ 为什么不用别的源(2026-09-16 实测):
   东财 push2his → ProxyError(实时的 push2delay 是通的, 只有历史端点被挡)
   iFinD history → errorcode -4318 本月额度已用完
   只剩腾讯 ifzq 可用。

⛔ 三个数据坑, 都踩过:
   ①必须用 day 不是 qfqday: qfq 是前复权, 判涨停要用不复权价
   ②代码前缀错了腾讯不报错只给别的股票的数据 → 前缀一律从 parquet 的 .SH/.SZ/.BJ 映射, 不猜
   ③腾讯会限流(lb5_peers 那次 49% 和 75% 失败)

⛔ 三个进程坑(2026-09-16 第一版就卡死在这):
   ①urlopen(timeout=) 只管单次 socket 操作, 挡不住整体 hang
     → 加 socket.setdefaulttimeout + 每次请求后主动 close
   ②每200条才 flush → 进度不可见, 卡死了看着像在跑
     → 改成每条都 flush, 慢一点但故障立刻可见(feedback_fault_must_shout)
   ③没有断点续跑 → 重启从头再来
     → 启动时读已有 jsonl, 跳过抓过的
"""
import json, sys, time, os, socket, urllib.request
import pandas as pd

SHARD, NSHARD = int(sys.argv[1]), int(sys.argv[2])
OUT = '/tmp/dhbr/qt0916'
os.makedirs(OUT, exist_ok=True)
BEG, END = '2026-09-05', '2026-09-15'      # 09-16未收盘, 当日bar不完整, 不取
PQ = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet'

socket.setdefaulttimeout(8)                 # ⛔全局兜底

df = pd.read_parquet(PQ, columns=['date', 'ticker', 'oshare'])
df['d'] = df['date'].astype(str).str[:10]
last = df[df['d'] == df['d'].max()]
univ = sorted(set(df['ticker'].unique()))
OSH = dict(zip(last['ticker'], last['oshare']))
del df

# ── 断点续跑: 已抓过的跳过 ──
done = set()
fp = f'{OUT}/shard_{SHARD}.jsonl'
if os.path.exists(fp):
    for ln in open(fp):
        try: done.add(json.loads(ln)['t'])
        except Exception: pass
print(f'[{SHARD}] 已抓过 {len(done)} 只, 跳过', flush=True)

_p = {'SH': 'sh', 'SZ': 'sz', 'BJ': 'bj'}
mine = [t for i, t in enumerate(univ) if i % NSHARD == SHARD and t not in done]

fo = open(fp, 'a')
fe = open(f'{OUT}/fail_{SHARD}.txt', 'a')
ok = fail = 0
t0 = time.time()
for i, tk in enumerate(mine):
    num, _, sfx = tk.partition('.')
    pre = _p.get(sfx)
    if not pre:
        continue
    code = pre + num
    url = (f'https://ifzq.gtimg.cn/appstock/app/fqkline/get?'
           f'param={code},day,{BEG},{END},20,')          # ⛔末尾空=不复权
    got = None
    for attempt in range(3):
        r = None
        try:
            r = urllib.request.urlopen(url, timeout=8)
            d = json.loads(r.read())['data'][code]
            got = d.get('day')
            break
        except Exception:
            time.sleep(0.8 * (attempt + 1))
        finally:
            if r is not None:
                try: r.close()
                except Exception: pass
    if not got:
        fe.write(tk + '\n'); fe.flush(); fail += 1
    else:
        fo.write(json.dumps({'t': tk, 'o': OSH.get(tk), 'k': got}) + '\n')
        fo.flush()                                       # ⛔每条都刷, 故障立刻可见
        ok += 1
    if i % 50 == 0:
        el = time.time() - t0
        print(f'[{SHARD}] {i}/{len(mine)} ok={ok} fail={fail} {el:.0f}s', flush=True)
    time.sleep(0.08)
fo.close(); fe.close()
print(f'[{SHARD}] DONE ok={ok} fail={fail} / {len(mine)}', flush=True)
