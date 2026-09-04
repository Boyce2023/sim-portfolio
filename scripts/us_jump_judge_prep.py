#!/usr/bin/env python3
"""昨夜跳涨股 逐只判断的准备材料 (2026-09-02 建, 9/3起每早跟在 us_track_daily.py 后面跑)
数据源=桌面「美股选股追踪.xlsx」Sheet1(us_track_daily 已追加当日跳涨), 本脚本只补新闻+基础率格子, 不重拉全宇宙价格(避免yf限流)。
用法: python3 us_jump_judge_prep.py [YYYY-MM-DD] [xlsx路径]  → stdout + /tmp/us_jump_prep_<date>.md
"""
import sys,os,datetime,openpyxl,yfinance as yf
XL=sys.argv[2] if len(sys.argv)>2 else os.path.expanduser('~/Desktop/Track/美股选股追踪.xlsx')
ws=openpyxl.load_workbook(XL,read_only=True,data_only=True)['1_跳涨10%以上']
rows=[r for r in ws.iter_rows(min_row=5,values_only=True) if r and r[0]]
def dstr(v): return v.strftime('%Y-%m-%d') if hasattr(v,'strftime') else str(v)[:10]
if len(sys.argv)>1:
    day=sys.argv[1]
else:
    day=dstr(rows[0][0])
    # ⛔2026-09-04: 避免"表没更新→重投昨天的文件"看起来像"今天没跳涨"。
    import datetime as _dt, zoneinfo
    et=_dt.datetime.now(zoneinfo.ZoneInfo('America/New_York')); d0=et.date()
    if et.hour<16 or et.weekday()>4: d0-=_dt.timedelta(days=1)
    while d0.weekday()>4: d0-=_dt.timedelta(days=1)
    expect=d0.isoformat()
    if day!=expect:
        print(f"⚠️ 表内最新跳涨日 {day} != 最近收盘交易日 {expect}: 说明 {expect} 零跳涨或表未更新。产出零跳涨说明文件。")
        open(f'/tmp/us_jump_prep_{expect}.md','w').write(
            f"# {expect} 跳涨≥10% 逐只判断准备 (共0只)\n\n"
            f"该交易日在1456只宇宙(市值≥50亿)中无单日涨幅≥10%的标的; 或跳涨表未更新。\n"
            f"表内最新跳涨日为 {day}。若怀疑是脚本问题, 跑 us_track_daily.py 看输出。\n")
        day=expect; hits=[]
hits=locals().get('hits') if isinstance(locals().get('hits'),list) else [r for r in rows if dstr(r[0])==day]
def bucket(mc,sec,pre):
    mc=mc or 0; pre=(pre or 0)*100
    m='>1000亿(52%为正)' if mc>=100 else ('300-1000亿(50%)' if mc>=30 else ('100-300亿(45%)' if mc>=10 else '50-100亿(43%)'))
    s={'Health Care':'医疗(54%,回撤最浅)','Technology':'科技(50%)','Consumer Discretionary':'可选消费(37%,最差)','Industrials':'工业(37%,最差)','Finance':'金融(43%)'}.get(sec,str(sec))
    pr='前1月已涨>40%(56%,动量延续但回撤深)' if pre>40 else ('前1月涨15-40%(48%)' if pre>15 else ('前1月涨0-15%(48%)' if pre>0 else '前1月下跌(42%,超额最差)'))
    return f'{m} · {s} · {pr}'

# ── 主线归因(板块共识层): 按 sector 与关键词给当日跳涨做聚类, 供判断时接共识 ──
def theme_note(hits):
    if not hits: return ''
    import collections
    # 纯加密(不做AI数据中心)
    CRYPTO={'MSTR','RIOT','CIFR','BMNR','COIN','GLXY','BLSH','BULL','CRCL','HOOD','MARA','CLSK','HUT',
            'BITF','HIVE','BTDR','BTBT','CAN','SDIG','NAKA','SBET','CEP'}
    # 双属性: 比特币矿工转AI数据中心, 归属取决于当天是BTC在动还是AI订单在动(research 2026-09-04提出)
    DUAL={'IREN','WULF','APLD','CORZ'}
    btc_chg=None
    try:
        import yfinance as _yf
        _h=_yf.Ticker('BTC-USD').history(period='5d')['Close'].dropna()
        if len(_h)>=2: btc_chg=(float(_h.iloc[-1])/float(_h.iloc[-2])-1)*100
    except Exception: pass
    tags=collections.Counter(); names=collections.defaultdict(list)
    for r in hits:
        t=r[1]; sec=str(r[3] or '')
        if t in DUAL:
            k = '加密链(矿工/交易所/券商/稳定币)' if (btc_chg is not None and btc_chg>5) else 'AI数据中心(矿转算力)'
            tags[k]+=1; names[k].append(t+'*')
        elif t in CRYPTO: tags['加密链(矿工/交易所/券商/稳定币)']+=1; names['加密链(矿工/交易所/券商/稳定币)'].append(t)
        elif 'Health' in sec: tags['医疗生物']+=1; names['医疗生物'].append(t)
        elif 'Techno' in sec: tags['科技']+=1; names['科技'].append(t)
        elif 'Energy' in sec or 'Utilit' in sec: tags['能源电力']+=1; names['能源电力'].append(t)
        elif 'Financ' in sec: tags['金融']+=1; names['金融'].append(t)
        else: tags[sec or '其他']+=1; names[sec or '其他'].append(t)
    parts=[f"{k} {v}只({'/'.join(names[k][:6])})" for k,v in tags.most_common()]
    top=tags.most_common(1)[0]
    lead = f"**当日主线: {top[0]}占 {top[1]}/{len(hits)}**。" if top[1]>=max(2,len(hits)*0.4) else "当日无单一主线, 分散。"
    btc_line = (f" 当日BTC {btc_chg:+.1f}%," + ("双属性股(标*)按BTC>5%归加密链。" if (btc_chg is not None and btc_chg>5) else "双属性股(标*)归AI数据中心。")) if btc_chg is not None else " (BTC数据未取到, 双属性股默认归AI数据中心)"
    return (f"\n## 主线归因(自动聚类, 判断时请接当时的板块共识)\n{lead} 分布: " + " ｜ ".join(parts) + "\n"
            + f"\n口径:{btc_line} ⛔本聚类只给当日横截面的共识, 不代表该板块叙事在转好或转坏, 那一层要另接。\n")

out=[f'# {day} 跳涨≥10% 逐只判断准备 (共{len(hits)}只; 基础率: 21日46%为正/中位-1.7%; 次日反应是最便宜的确认信号; 详见 research-notes/us-database/2026-09-03_跳涨后走势_基础率.md)\n']
for r in hits:
    d,t,name,sec,pc,cc,chg,now,mc,pre1,post1,desc=(list(r)+[None]*12)[:12]
    try: news=[(n.get('title') or n.get('content',{}).get('title')) for n in yf.Ticker(t).news[:5]]
    except Exception: news=[]
    out.append(f"## {t} {name}  {(chg or 0)*100:+.1f}%  收{cc}  市值{mc}B  {sec}\n- 这家做什么: {desc or ''}\n- 前1月 {(pre1 or 0)*100:+.1f}% | 格子: {bucket(mc,sec,pre1)}\n- 新闻: " + (' ｜ '.join(x for x in news if x) or '(yf无)') + "\n- 原因:  \n- 判断(延续/回吐/钉住):  \n- 依据:  \n- 确认信号: 次日>+3%→52%为正; 次日<-3%→48%再回吐>10%\n")
md='\n'.join(out)+theme_note(hits); print(md); open(f'/tmp/us_jump_prep_{day}.md','w').write(md)
