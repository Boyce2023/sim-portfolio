"""把 A股日线从 09-08 补到 09-15 (东财 push2his, 不复权)

⛔ 2026-09-16 选源经过(三个源全试过, 别再走回头路):
   腾讯 ifzq.gtimg.cn  → HTTP 501, 走代理绕代理都一样(域名被 TUN fake-IP 劫持到 198.18.0.232,
                         应用层 ProxyHandler 绕不掉 TUN), 且只给6字段没有成交额换手率
   iFinD history       → errorcode -4318 本月额度已用完
   东财 push2his       → ⭐可用, 前提是 import requests 之前设 NO_PROXY='*'
                         (memory/reference_eastmoney_proxy_fix.md 第18行早就写了, 我没去取,
                          先用裸 akshare 撞了 ProxyError 才绕回来)

⛔ 为什么这个源更好: 返回11字段含成交额与换手率, 市值可用 amt/(turn/100) 直接算,
   与 univ*.db 完全同一个公式 —— 今天上午那个"换手率单位不同导致市值差100倍"的坑,
   在这条路径上从源头就不存在。

⛔ 进程纪律(第一版腾讯脚本卡死的教训):
   每条都 flush(故障立刻可见) + 断点续跑 + 失败单独记录 + 全局 socket 超时

用法: python3 fetch_em.py <分片号> <总分片数>
"""
import os
os.environ['NO_PROXY'] = '*'      # ⛔必须在 import requests 之前
os.environ['no_proxy'] = '*'

import json, sys, time, socket
import requests
import pandas as pd

SHARD, NSHARD = int(sys.argv[1]), int(sys.argv[2])
OUT = '/tmp/dhbr/em0916'
os.makedirs(OUT, exist_ok=True)
BEG, END = '20260905', '20260915'   # 09-16未收盘, 当日bar不完整, 不取
PQ = '/Users/huaichuaibeimeng/claude-projects/sim-portfolio/data/cn_hk_price_db/a_daily.parquet'
URL = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
socket.setdefaulttimeout(10)

df = pd.read_parquet(PQ, columns=['ticker'])
univ = sorted(set(df['ticker'].unique()))
del df

def secid(tk):
    """⛔东财 secid: 沪(6开头)=1., 深/创/北=0.。前缀错了不报错只给别的股票, 必须验过再用。"""
    num, _, sfx = tk.partition('.')
    return ('1.' if sfx == 'SH' else '0.') + num

done = set()
fp = f'{OUT}/shard_{SHARD}.jsonl'
if os.path.exists(fp):
    for ln in open(fp):
        try: done.add(json.loads(ln)['t'])
        except Exception: pass
print(f'[{SHARD}] 已抓过 {len(done)} 只, 跳过', flush=True)

mine = [t for i, t in enumerate(univ) if i % NSHARD == SHARD and t not in done]
P = {'fields1': 'f1,f2,f3,f4,f5,f6',
     'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f116',
     'ut': '7eea3edcaed734bea9cbfc24409ed989',
     'klt': '101', 'fqt': '0', 'beg': BEG, 'end': END}

fo = open(fp, 'a'); fe = open(f'{OUT}/fail_{SHARD}.txt', 'a')
ses = requests.Session()
ok = fail = 0
t0 = time.time()
for i, tk in enumerate(mine):
    got = None
    for attempt in range(3):
        try:
            p = dict(P); p['secid'] = secid(tk)
            r = ses.get(URL, params=p, timeout=10)
            d = r.json().get('data')
            if d:
                got = {'n': d.get('name'), 'k': d.get('klines', [])}
            break
        except Exception:
            time.sleep(0.6 * (attempt + 1))
    if got is None:
        fe.write(tk + '\n'); fe.flush(); fail += 1
    else:
        fo.write(json.dumps({'t': tk, **got}, ensure_ascii=False) + '\n')
        fo.flush()
        ok += 1
    if i % 50 == 0:
        print(f'[{SHARD}] {i}/{len(mine)} ok={ok} fail={fail} {time.time()-t0:.0f}s', flush=True)
    time.sleep(0.05)
fo.close(); fe.close()
print(f'[{SHARD}] DONE ok={ok} fail={fail} / {len(mine)}', flush=True)
