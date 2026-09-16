#!/usr/bin/env python3
"""刷新 AI 护城河选股 csv 的行情五列(现价$/市值$B/近1月%/PE_TTM/PB), 文本列不动。
⛔断言新价格日 > 旧价格日才覆盖, 否则退出码2不写(防止美股未收盘时拿同一天数据"刷新"成假新鲜)。
用法: python3 ai_moat_refresh_prices.py [csv路径]  退出码 0=已刷新 / 2=没有更新的收盘 / 3=有 ticker 取不到价
"""
import sys, csv, json, warnings, os, datetime; warnings.filterwarnings('ignore')
import yfinance as yf
P=sys.argv[1] if len(sys.argv)>1 else os.path.expanduser('~/claude-projects/sim-portfolio/research-notes/us-database/ai_moat_us.csv')
META=P+'.meta.json'
rows=list(csv.DictReader(open(P,encoding='utf-8'))); cols=list(rows[0].keys())
tk=sorted({r['代码'] for r in rows})
old_date=json.load(open(META))['price_date'] if os.path.exists(META) else '2026-09-14'
# ⛔2026-09-16: 原版只用日线, 而 yfinance 的日线在收盘后数小时仍是 NaN(09-15 四只抽样全 NaN),
#   于是把"9/15 已收盘"读成"末日还是 9/14"并退出。这与 us_disaster_check.py 09-09 修过的是同一个坑,
#   我昨晚写这个脚本时没复用它。现改为直接调用那两个函数: 交易日从 SPY 5分钟线读出, 缺日线时用
#   常规时段(<=16:00)分钟线末根补真收盘价, 不用盘后价。
import importlib.util
_spec=importlib.util.spec_from_file_location('udc', os.path.join(os.path.dirname(os.path.abspath(__file__)),'us_disaster_check.py'))
_udc=importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_udc)
target,terr=_udc.last_completed_session()
if terr:
    print(f"⛔ 判不出最近已收盘交易日: {terr}"); sys.exit(2)
new_date=str(target)
if new_date<=old_date:
    print(f"没有更新的收盘: 最近收盘日 {new_date} <= 上次 {old_date}, 不覆盖"); sys.exit(2)
prices=_udc.fetch_prices(tk, target)                      # {ticker:(price,date)}
hist=yf.download(tk,period='3mo',auto_adjust=False,progress=False)['Close']
miss=[]
for r in rows:
    t=r['代码']; got=prices.get(t)
    if not got or got[1]!=target: miss.append(t); continue
    px_now=float(got[0])
    h=hist[t].dropna() if t in hist.columns else None      # 近1月% 用日线回看22根, 末根用今日实际收盘
    if h is None or len(h)<21: miss.append(t); continue
    base=float(h.iloc[-21]) if str(h.index[-1].date())==new_date else float(h.iloc[-21])
    info=yf.Ticker(t).info
    r['现价$']=round(px_now,2); r['近1月%']=round(px_now/base-1,4)
    r['市值$B']=round(info['marketCap']/1e9,1) if info.get('marketCap') else ''
    r['PE_TTM']=round(info['trailingPE'],1) if info.get('trailingPE') else ''
    r['PB']=round(info['priceToBook'],2) if info.get('priceToBook') else ''
if miss:
    print(f"⛔ {len(miss)} 只取不到 {new_date} 的收盘, 不覆盖: {miss}"); sys.exit(3)
tmp=P+'.tmp'
with open(tmp,'w',newline='',encoding='utf-8') as fh:
    w=csv.DictWriter(fh,fieldnames=cols); w.writeheader(); w.writerows(rows)
os.replace(tmp,P); json.dump({'price_date':new_date,'refreshed_at':datetime.datetime.now().isoformat(timespec='seconds')},open(META,'w'))
print(f"已刷新 {len(rows)} 行, 价格日 {old_date} → {new_date}: {P}"); sys.exit(0)
