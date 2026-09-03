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
day=sys.argv[1] if len(sys.argv)>1 else dstr(rows[0][0])
hits=[r for r in rows if dstr(r[0])==day]
def bucket(mc,sec,pre):
    mc=mc or 0; pre=(pre or 0)*100
    m='>1000亿(52%为正)' if mc>=100 else ('300-1000亿(50%)' if mc>=30 else ('100-300亿(45%)' if mc>=10 else '50-100亿(43%)'))
    s={'Health Care':'医疗(54%,回撤最浅)','Technology':'科技(50%)','Consumer Discretionary':'可选消费(37%,最差)','Industrials':'工业(37%,最差)','Finance':'金融(43%)'}.get(sec,str(sec))
    pr='前1月已涨>40%(56%,动量延续但回撤深)' if pre>40 else ('前1月涨15-40%(48%)' if pre>15 else ('前1月涨0-15%(48%)' if pre>0 else '前1月下跌(42%,超额最差)'))
    return f'{m} · {s} · {pr}'
out=[f'# {day} 跳涨≥10% 逐只判断准备 (共{len(hits)}只; 基础率: 21日46%为正/中位-1.7%; 次日反应是最便宜的确认信号; 详见 research-notes/us-database/2026-09-03_跳涨后走势_基础率.md)\n']
for r in hits:
    d,t,name,sec,pc,cc,chg,now,mc,pre1,post1,desc=(list(r)+[None]*12)[:12]
    try: news=[(n.get('title') or n.get('content',{}).get('title')) for n in yf.Ticker(t).news[:5]]
    except Exception: news=[]
    out.append(f"## {t} {name}  {(chg or 0)*100:+.1f}%  收{cc}  市值{mc}B  {sec}\n- 这家做什么: {desc or ''}\n- 前1月 {(pre1 or 0)*100:+.1f}% | 格子: {bucket(mc,sec,pre1)}\n- 新闻: " + (' ｜ '.join(x for x in news if x) or '(yf无)') + "\n- 原因:  \n- 判断(延续/回吐/钉住):  \n- 依据:  \n- 确认信号: 次日>+3%→52%为正; 次日<-3%→48%再回吐>10%\n")
md='\n'.join(out); print(md); open(f'/tmp/us_jump_prep_{day}.md','w').write(md)
