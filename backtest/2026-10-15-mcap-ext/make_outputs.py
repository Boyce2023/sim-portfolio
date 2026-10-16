#!/opt/homebrew/bin/python3.13
"""由 firstboard_ext.parquet 生成: ① Track/2_结论/打板市值研究.xlsx(封面+三表, 版式沿用原表) ② output/表2_打板市值研究.html(沿用原网页配色与结构).
旧版先移入 output/_归档_底稿与旧版/ 并带日期."""
import pandas as pd,numpy as np,statistics as st,os,shutil,datetime
from openpyxl import Workbook
from openpyxl.styles import Font,Alignment
R=pd.read_parquet('firstboard_ext.parquet')
MS=sorted(R.m.unique()); LASTM=MS[-1]; LASTD=R[R.m==LASTM].date.max(); LASTN=R[R.m==LASTM].date.nunique()
DBLAST=pd.read_parquet('../../data/cn_hk_price_db/a_daily.parquet',columns=['date']).date.max().strftime('%Y-%m-%d')
M10=[(i,i+10) for i in range(10,300,10)]
UB=[(-1e9,0,'≤0'),*[(i,i+10,f'{i}-{i+10}') for i in range(0,100,10)],(100,1e9,'100+')]
def inb(v,a,b): return (v<=0) if b==0 else ((v>a)&(v<=b))
ROWS=[(f'{a}-{b}亿',R[(R.mcap>=a)&(R.mcap<b)]) for a,b in M10]
in29=sum(len(g) for _,g in ROWS); out29=len(R)-in29
MSL=[m[2:4]+'/'+m[5:7] for m in MS]
TODAY=datetime.date.today().isoformat()
# ---------- xlsx ----------
TNR=lambda sz=11,b=False: Font(name='Times New Roman',size=sz,bold=b)
def sheet(wb,title,name,note,header,rows,lastrow):
    ws=wb.create_sheet(name); ws.column_dimensions['A'].width=1.8; ws.column_dimensions['B'].width=12
    from openpyxl.utils import get_column_letter
    for j in range(3,len(header)+2): ws.column_dimensions[get_column_letter(j)].width=11
    ws.cell(1,2,title).font=TNR(11,True); ws.cell(2,2,note).font=TNR()
    for j,h in enumerate(header,2): c=ws.cell(4,j,h); c.font=TNR(11,True)
    r=5
    for row in rows+[lastrow]:
        for j,v in enumerate(row,2):
            c=ws.cell(r,j,v); c.font=TNR(11,j==2 or row is lastrow)
        r+=1
    ws.freeze_panes='C5'
wb=Workbook(); cov=wb.active; cov.title='封面'
cov.column_dimensions['A'].width=1.8; cov.column_dimensions['B'].width=14; cov.column_dimensions['C'].width=90
lines=[('类型','规律实证 · 短线'),('市场','A股'),('状态','稳定结论, 按需延长'),('负责','astock'),
 ('结论','龙头起爆前流通市值集中在30到50亿; 首板后10日最大涨幅按市值分层见表一; 每月首板数与平均连板数按市值分层见表二、表三; 流通市值10到30亿首板数与上证指数对照见表四'),
 ('最后更新',TODAY),
 ('样本范围',f'2022年1月至{LASTM[:4]}年{int(LASTM[5:])}月, 首板样本{len(R)}个, 流通市值取首板当日; 涨幅从首板收盘价起算, 取后10个交易日内最大涨幅; 行情截至{DBLAST}'),
 ('涨跌幅制度','按各股当日实际适用涨跌幅判定涨停, 含风险警示股; 风险警示身份按逐日记录判定; 沪深主板风险警示股2026年7月6日由5%上调至10%, 跨该日按日分段; 创业板科创板20%, 北交所30%; 新股上市前5个交易日不设涨跌幅, 不计入'),
 ('数据覆盖',f'北交所行情截至2026年9月8日, 此后北交所首板未计入; {LASTM} 为月内至{LASTD}的{LASTN}个交易日, 不是完整月')]
cov.cell(1,2,'打板市值研究 · 首板后10日最大涨幅 × 流通市值').font=TNR(16,True)
for i,(k,v) in enumerate(lines,3):
    cov.cell(i,2,k).font=TNR(14); c=cov.cell(i,3,v); c.font=TNR(14); c.alignment=Alignment(wrap_text=True,vertical='top')
# 表一
base={l:round(inb(R.hi10,a,b).mean()*100,1) for a,b,l in UB}
t1=[]
for lab,g in ROWS:
    if len(g)==0: t1.append([lab,0]+['']*len(UB)+['']); continue
    t1.append([lab,len(g)]+[round(inb(g.hi10,a,b).mean()*100,1) for a,b,_ in UB]+[round(g.final.mean(),2)])
last1=['全样本',len(R)]+[base[l] for _,_,l in UB]+[round(R.final.mean(),2)]
sheet(wb,'打板 · 首板后10日最大涨幅 × 流通市值 · 一 市值 × 涨幅区间','1_市值×涨幅区间',
      f'首板后10日内最大涨幅按流通市值分层, 单位为只数与百分比; 29档覆盖流通市值10到300亿共{in29}只, 全样本行含档外{out29}只({out29/len(R)*100:.1f}%); {LASTM[2:4]}/{LASTM[5:]} 为不完整月, 该月首板后不足10个交易日, 涨幅分布被系统性低估',
      ['流通市值','样本']+[f'{l}%' for _,_,l in UB]+['平均连板数'],t1,last1)
# 表二
cnt=R.groupby('m').size()
t2=[[lab]+[int((g.m==m).sum()) for m in MS]+[len(g)] for lab,g in ROWS]
sheet(wb,'打板 · 首板后10日最大涨幅 × 流通市值 · 二 市值 × 月份 首板数','2_市值×月份首板数',
      f'每月首板数按流通市值分层, 单位为只数; 最后一列为合计, 最后一行为月合计(含档外, 与29档之和不等); {LASTM[2:4]}/{LASTM[5:]} 为月内至数据截止日, 本表首板只数不受影响但不是完整月',
      ['流通市值']+MSL+['合计'],t2,['月合计']+[int(cnt[m]) for m in MS]+[len(R)])
# 表三
def avg(s): return round(s.mean(),2) if len(s)>=5 else '·'
t3=[[lab]+[avg(g[g.m==m].final) for m in MS]+[round(g.final.mean(),2) if len(g) else '·'] for lab,g in ROWS]
sheet(wb,'打板 · 首板后10日最大涨幅 × 流通市值 · 三 市值 × 月份 平均连板数','3_市值×月份平均连板数',
      f'每月首板的平均连板数按流通市值分层, 样本少于5只的格子记为点; 最后一行为全期; {LASTM[2:4]}/{LASTM[5:]} 为不完整月, 平均连板数被系统性低估',
      ['流通市值']+MSL+['全期'],t3,['全期']+[round(R[R.m==m].final.mean(),2) for m in MS]+[round(R.final.mean(),2)])

# 表四 数据: 10到30亿首板数 与 上证指数月末收盘
import subprocess,json
_o=subprocess.run(['curl','-s','-m','15','https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000001,month,2021-12-01,2026-12-31,100,qfq'],capture_output=True,text=True,env={k:v for k,v in os.environ.items() if 'proxy' not in k.lower()}).stdout
_k=json.loads(_o)['data']['sh000001']; _k=_k.get('month') or _k.get('qfqmonth')
SH=pd.Series({x[0][:7]:float(x[2]) for x in _k})
S1030=R[(R.mcap>=10)&(R.mcap<30)].groupby('m').size().reindex(MS,fill_value=0)
T4=pd.DataFrame({'月份':MS,'10到30亿首板数':S1030.values,'上证指数月末收盘':[SH.get(m) for m in MS]})
ws4=wb.create_sheet('4_10到30亿首板与上证')
ws4.column_dimensions['A'].width=1.8
for j,w in zip('BCD',(12,16,18)): ws4.column_dimensions[j].width=w
ws4.cell(1,2,'打板 · 首板后10日最大涨幅 × 流通市值 · 四 流通市值10到30亿首板数 与 上证指数').font=TNR(11,True)
ws4.cell(2,2,f'每月流通市值10到30亿首板只数(表二前两档之和)与上证指数月末收盘; {LASTM[2:4]}/{LASTM[5:]} 为不完整月, 上证取最近收盘').font=TNR()
for j,h in enumerate(T4.columns,2): ws4.cell(4,j,h).font=TNR(11,True)
for i,row in enumerate(T4.itertuples(index=False),5):
    for j,v in enumerate(row,2): ws4.cell(i,j,v).font=TNR(11,j==2)
ws4.freeze_panes='C5'
# 图
import sys as _s; _s.path.insert(0,os.path.expanduser('~/claude-projects/.build_charts'))
import chartstyle as cs, matplotlib.pyplot as plt, matplotlib.dates as mdates
x=pd.to_datetime([m+'-15' for m in MS])
fig,ax=cs.fig_ax(10.5,4.2)
cols=[cs.STEEL]*(len(MS)-1)+['#B9C7D6']
ax.bar(x,S1030.values,width=22,color=cols,label='流通市值10到30亿 首板数(左轴, 只)')
ax.set_ylabel('首板数(只)',color=cs.STEEL)
ax2=ax.twinx(); ax2.plot(x,T4['上证指数月末收盘'].values,color=cs.NAVY,lw=1.8,label='上证指数 月末收盘(右轴)')
ax2.set_ylabel('上证指数',color=cs.NAVY); ax2.grid(False)
for sp in ['top']: ax2.spines[sp].set_visible(False)
ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1,4,7,10])); ax.xaxis.set_major_formatter(mdates.DateFormatter('%y/%m'))
h1,l1=ax.get_legend_handles_labels(); h2,l2=ax2.get_legend_handles_labels(); ax.legend(h1+h2,l1+l2,loc='upper left')
ax.set_title('流通市值10到30亿首板数 与 上证指数 (月度)',loc='left',color=cs.NAVY,fontweight='bold')
fig.text(0.01,-0.02,f'来源: 本地A股日线库首板统计(口径同表二) · 上证指数取腾讯月线 · {LASTM[2:4]}/{LASTM[5:]} 浅色柱为不完整月(截至{LASTD})',fontsize=8,color=cs.CAP)
fig.tight_layout(); fig.savefig('chart4.png',dpi=110,bbox_inches='tight'); fig.savefig('chart4.svg',format='svg',bbox_inches='tight'); plt.close(fig)

XL=os.path.expanduser('~/Desktop/Track/2_结论/打板市值研究.xlsx'); HT=os.path.expanduser('~/claude-projects/sim-portfolio/output/表2_打板市值研究.html')
ARC=os.path.expanduser('~/claude-projects/sim-portfolio/output/_归档_底稿与旧版/')
import sys
if '--write' in sys.argv:
    for p in (XL,HT):
        if os.path.exists(p):
            b,e=os.path.splitext(os.path.basename(p)); dst=ARC+f'{b}_2025-01至2026-09版_{datetime.date.today():%Y%m%d}{e}'
            if not os.path.exists(dst): shutil.copy2(p,dst); print('归档',dst)
    wb.save(XL); print('写入',XL)
else:
    wb.save('/private/tmp/claude-501/打板市值研究_预览.xlsx'); print('预览已存 /private/tmp/claude-501/打板市值研究_预览.xlsx')
# ---------- html: 复用原网页的结构与配色 ----------
src=open('../2026-09-07-mcap/report2.py').read()
recs=R.assign(mcap=R.mcap.astype(float)).to_dict('records')
import json; json.dump([{k:(v if not isinstance(v,(np.floating,np.integer)) else v.item()) for k,v in r.items()} for r in recs],open('/private/tmp/claude-501/grid_ext.json','w'),default=str)
src=src.replace("R=json.load(open('/tmp/grid_v5.json'))","R=json.load(open('/private/tmp/claude-501/grid_ext.json'))")
src=src.replace("open('output/表2_打板市值研究.html','w')",f"open('{HT if '--write' in sys.argv else '/private/tmp/claude-501/表2_打板市值研究_预览.html'}','w')")
# 说明段改为当前口径, 不保留施工记录
import re
start=src.index('<div class="doc-sub" style="color:#C0392B">⛔ {NOFQ_FROM}'); end=src.index('<hr class="rule-navy">',start)
note=('<div class="doc-sub" style="color:#C0392B">涨跌幅制度: 按各股当日实际适用的涨跌幅判定涨停, 含风险警示股, 风险警示身份按逐日记录判定; 沪深主板风险警示股二零二六年七月六日起由百分之五上调至百分之十, 跨该日按日分段; 创业板与科创板为百分之二十, 北交所为百分之三十; 新股上市前五个交易日不设涨跌幅, 不计入。'
      '本表包含风险警示股, 市面上的涨停池数据通常将其排除, 逐日核对时多出的风险警示股属于口径差异。北交所行情截至二零二六年九月八日, 此后北交所首板未计入。</div>')
src=src[:start]+note+src[end:]
src=src.replace('⛔末月数据口径','末月数据口径').replace('<div class="doc-sub" style="color:#C0392B">末月','<div class="doc-sub" style="color:#C0392B">末月')
src=src.replace("print(f'ok","print(f'html ok")
exec(compile(src,'report_ext','exec'),{'__name__':'__main__'})

# 网页末尾加第四节图
_hp=HT if '--write' in sys.argv else '/private/tmp/claude-501/表2_打板市值研究_预览.html'
_h=open(_hp).read(); _svg=open('chart4.svg').read(); _svg=_svg[_svg.index('<svg'):]
_sec=('<h2>四 流通市值10到30亿首板数 与 上证指数</h2>'+f'<div style="max-width:1100px">{_svg}</div>'
      +'<div class="lg">柱为每月流通市值10到30亿的首板只数(表二前两档之和), 线为上证指数月末收盘; 末月浅色柱为不完整月。</div>')
_h=_h.replace('</div></body></html>',_sec+'</div></body></html>'); open(_hp,'w').write(_h); print('第四节已加入',_hp)
