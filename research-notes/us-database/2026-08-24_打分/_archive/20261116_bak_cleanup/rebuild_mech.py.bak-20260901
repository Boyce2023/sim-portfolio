# -*- coding: utf-8 -*-
"""重建机械层(agent判断分已在 agent_scores.json, 此脚本只补可算的部分)
⛔教训(2026-08-24): 首版把工作产物全写/tmp, session重启后全丢。
   文件落点铁律说的是"临时文件"进/tmp; 工作产物属于项目, 必须落项目目录。"""
import json, yfinance as yf, warnings, os
warnings.filterwarnings('ignore')
D=os.path.dirname(os.path.abspath(__file__))
A=json.load(open(os.path.join(D,'agent_scores.json')))
ST='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/portfolio_state.json'
st=json.load(open(ST))['accounts']['us']
pos=st['positions']; items=list(pos.values()) if isinstance(pos,dict) else pos
HOLD={p['ticker']:p for p in items}
tk=sorted(A.keys())
print(f"重建 {len(tk)} 只机械层...", flush=True)
out={}
for i in range(0,len(tk),120):
    b=tk[i:i+120]
    h=yf.download(b,period='1y',progress=False,auto_adjust=True,threads=True)['Close']
    for t in b:
        try:
            s=h[t].dropna()
            if len(s)<60: continue
            cur=float(s.iloc[-1]); s26=s[s.index>='2026-01-01']
            h25=float(s.iloc[-26:-1].max())
            out[t]=dict(t=t,px=round(cur,2),
                d30=round((cur/float(s.iloc[-22])-1)*100,2),
                d5=round((cur/float(s.iloc[-6])-1)*100,2),
                ytd=round((cur/float(s26.iloc[0])-1)*100,2),
                dh3=round((cur/float(s.iloc[-63:].max())-1)*100,2),
                dh52=round((cur/float(s.max())-1)*100,2),
                brk=cur>h25, h25=round(h25,2))
        except Exception: pass
    print(f"  {min(i+120,len(tk))}/{len(tk)}", flush=True)
# 估值
import concurrent.futures as cf
def vi(t):
    try:
        i=yf.Ticker(t).fast_info
        mc=i['marketCap']
    except Exception: mc=None
    try:
        f=yf.Ticker(t).info
        p=f.get('currentPrice') or f.get('regularMarketPrice'); te=f.get('trailingEps'); fe=f.get('forwardEps')
        # ⛔2026-08-27修: 原版对230只并发调 tk.cashflow/tk.financials, 实测全部返回空
        #   (单只串行能取到, 并发就失败)。改用 info 里已有的字段, 不另开请求。
        #   口径: 经营现金流/净利, 不减capex——衡量"利润是不是真现金", 不掺"在不在扩产"。
        fcf_conv=None
        try:
            ocf=f.get('operatingCashflow'); ni=f.get('netIncomeToCommon')
            if ocf and ni and ni!=0: fcf_conv=round(ocf/ni,2)
        except Exception: pass
        return t,dict(mc=mc,name=f.get('longName') or t,sector=f.get('sector'),industry=f.get('industry'),
                      ttm_eps=te, fwd_eps=fe, fcf_conv=fcf_conv,
                      fwd_pe=round(p/fe,2) if (p and fe and fe>0) else None,
                      impl_g=round((fe/te-1)*100,1) if (fe and te and te>0) else None)
    except Exception: return t,dict(mc=mc)
with cf.ThreadPoolExecutor(max_workers=12) as ex:
    for t,d in ex.map(vi,tk):
        if t in out: out[t].update(d)
for t,x in out.items():
    x['held']= t in HOLD
    if x['held']:
        p=HOLD[t]; sh=p['shares']
        x['weight']=round(sh*p['current_price']/st['total_assets']*100,1)
        cb=p.get('cost_basis',0)/sh if p.get('cost_basis') else p.get('avg_cost')
        x['unreal']=round((p['current_price']/cb-1)*100,1)
json.dump(list(out.values()),open(os.path.join(D,'mech_input.json'),'w'),ensure_ascii=False)
print(f"✓ 机械层重建完成 {len(out)} 只 → mech_input.json", flush=True)
