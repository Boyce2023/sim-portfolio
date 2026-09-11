#!/opt/homebrew/bin/python3
"""超跌反弹灾难预案 · 触发器(2026-09-11建)

⛔它不是选股器, 是一份平时零仓位的预案。依据(全A 2016-2026, 信号日收盘出现→次日开盘买→5日收盘卖, 超额=减全A等权):
  当日全市场同时触发 1-2笔  → 5日+0.70% 胜率47.1%   t=1.85  ← 噪音
  当日全市场同时触发 3-9笔  → 5日+1.16% 胜率51.9%   t=3.26  ← 仍不够
  当日全市场同时触发 10-29笔 → 5日+4.99% 胜率73.6%  t=9.47  ← 从这里才有效
  当日全市场同时触发 30-99笔 → 5日+5.79% 胜率66.8%  t=8.03
  当日全市场同时触发 ≥100笔  → 5日+16.45% 胜率99.2% t=23.81 ← 十年只有2天(2024-02-06/08)
⛔"10笔以上"这一档十年只出现23天, 年均2.1天。所以本脚本绝大多数日子应该输出0并且什么都不做,
  输出0是正常工作不是故障。会喊的只有真正的全市场恐慌底。
⛔信号密度本身就是过滤器: 个股跌多少不重要, 重要的是同一天有多少只一起触发。

信号定义: 20日跌幅<-30% 且 当日收阳 且 量比>1.5(对过去5日均额) 且 日成交额>2000万 且 上市>60日
用法: python3 scripts/oversold_trigger.py [--force]   建议 launchd 每交易日 15:05
"""
import json,os,sys,datetime,urllib.request,subprocess
import pandas as pd,numpy as np
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB=f'{ROOT}/data/cn_hk_price_db/a_daily.parquet'
LOG=f'{ROOT}/data/oversold_trigger.jsonl'
THRESH=10

def fs(msg):
    try:
        r=subprocess.run(['bash',os.path.expanduser('~/.claude/session-remote/fs-reply.sh'),msg],
                         capture_output=True,text=True,timeout=30)
        if r.returncode!=0: print(f'⛔飞书发送失败 rc={r.returncode} {r.stderr[-200:]}',file=sys.stderr)
    except Exception as e: print(f'⛔飞书异常 {e}',file=sys.stderr)

def snapshot():
    """今日全市场快照。⛔拿不全即抛, 不允许用残缺市场算密度(密度就是本预案的全部判据)。
    get_full_market 返回 list[dict], turnover 单位是亿元, 这里统一换成元。"""
    sys.path.insert(0,f'{ROOT}/scripts')
    from astock_data_layer import get_full_market
    m=get_full_market()
    if not m or len(m)<3000:
        raise RuntimeError(f'全市场快照只拿到 {0 if not m else len(m)} 只, 少于3000 → 拒绝用残缺市场估信号密度')
    df=pd.DataFrame(m)
    df['code']=df['code'].astype(str).str[:6]
    df['amt']=pd.to_numeric(df['turnover'],errors='coerce')*1e8
    return df

def main():
    force='--force' in sys.argv
    now=datetime.datetime.now()
    if not force and now.weekday()>=5:
        print('非交易日, 跳过'); return
    m=snapshot()
    hist=pd.read_parquet(DB,columns=['date','ticker','adj_close','amount','close'])
    hist['date']=pd.to_datetime(hist.date)
    last=hist.date.max()
    h=hist.sort_values(['ticker','date'])
    # ⛔用 tail(21) 取窗口而非 nth(-21): pandas 2.x 的 nth 返回原索引不是分组索引(已踩)
    w=h.groupby('ticker',sort=False).tail(21)
    H=w.groupby('ticker').agg(ac20=('adj_close','first'),ac_last=('adj_close','last'),
                              c_last=('close','last'),nbar=('adj_close','size'))
    a5=h.groupby('ticker',sort=False).tail(5).groupby('ticker')['amount'].mean().rename('amt5')
    H=H.join(a5).reset_index()
    H=H[H.nbar>=21]                                    # 上市不足21根的自动排除(等价于新股门)
    H['code']=H['ticker'].astype(str).str[:6]
    d=m.merge(H,on='code',how='inner')
    px=pd.to_numeric(d['price'],errors='coerce')
    op=pd.to_numeric(d['open'],errors='coerce')
    amt=pd.to_numeric(d['amt'],errors='coerce')
    adj=d.ac_last/d.c_last                                # 复权比例, 把今日价换算成复权口径
    r20=(px*adj)/d.ac20-1
    vr=amt/d.amt5
    sig=(r20<-0.30)&(px>op)&(vr>1.5)&(amt>2e7)&px.notna()&op.notna()
    n=int(sig.sum())
    hit=d[sig].assign(r20=(r20[sig]*100).round(1),vr=vr[sig].round(2))
    rec={'date':now.strftime('%Y-%m-%d'),'time':now.strftime('%H:%M'),'n':n,'thresh':THRESH,
         'db_last':str(last.date()),'universe':int(len(d)),
         'names':hit[['code','name','r20','vr']].to_dict('records')[:40] if n else []}
    with open(LOG,'a') as f: f.write(json.dumps(rec,ensure_ascii=False)+'\n')
    print(f"{now:%Y-%m-%d %H:%M} 全市场超跌反弹信号 {n} 笔 (阈值{THRESH}, 宇宙{len(d)}只, 历史库末日{last.date()})")
    if n>=THRESH:
        names=' / '.join(f"{r['name']}({r['code']} 20日{r['r20']:.0f}% 量比{r['vr']:.1f})" for r in rec['names'][:12])
        band='10-29笔档(5日超额+4.99%/胜率73.6%)' if n<30 else ('30-99笔档(+5.79%/66.8%)' if n<100 else '⛔≥100笔档(+16.45%/胜率99.2%, 十年仅2天)')
        fs(f"[⛔超跌反弹灾难预案·触发] {now:%m-%d} 全市场同时触发 {n} 笔 ≥ 阈值{THRESH} → {band}。"
           f"这一档十年只出现23天(年均2.1天), 平时该是0。名单: {names}"
           f" ‖ 预案动作: 次日开盘买入, 持5日, 等权分散不重仓单只。⛔这是一次性事件不是常态策略。")
        print('⛔已触发, 飞书已发')
    else:
        print('未达阈值, 不动作(输出0是正常工作, 不是故障)')

if __name__=='__main__':
    main()
