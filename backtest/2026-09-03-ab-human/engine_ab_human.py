#!/usr/bin/env python3
"""AB合流·真人版 (2026-09-03 Buwen). 只用日线, 严格PIT, 真人排板成交模型。
用法: python3 engine_ab_human.py <db> 2025-01-01 2025-12-31"""
import sys,sqlite3,json,collections,statistics as st
B='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/'
IND=json.load(open(B+'ind_map.json'))
RANGE_N=8; SLOTS=3; CAP=1e6
COMM,COMM_MIN,TRANSFER,STAMP=0.0003,5.0,0.00001,0.0005; SLIP_SELL=0.005; SLIP_OPENBUY=0.003
def fee(a,sell): return max(a*COMM,COMM_MIN)+a*TRANSFER+(a*STAMP if sell else 0)
def limp(code,st_): return 0.05 if st_ else (0.199 if code[3:5] in ('30','68') else 0.099)
def is_lim(price,pc,L): return price>=round(pc*(1+L),2)-0.02 and price/pc-1>=L-0.004   # 前复权价差容差2分+比例双判(2026-09-03修)
def touched(high,pc,L): return is_lim(high,pc,L)
def load(db,m0,m1):
    con=sqlite3.connect(db); by=collections.defaultdict(list)
    for r in con.execute("select code,date,open,high,low,close,preclose,volume,amount,turn,isST from k where preclose>0 order by code,date"): by[r[0]].append(r)
    days=sorted({r[1] for bars in by.values() for r in bars})
    return by,days
def run(db,m0,m1):
    by,days=load(db,m0,m1)
    idx={c:{b[1]:i for i,b in enumerate(bars)} for c,bars in by.items()}
    # 每日涨停/跌停家数与行业涨停
    ztc=collections.Counter(); dtc=collections.Counter(); ztind=collections.defaultdict(collections.Counter)
    for c,bars in by.items():
        for b in bars:
            L=limp(c,b[10]); 
            if is_lim(b[5],b[6],L): ztc[b[1]]+=1; ztind[b[1]][IND.get(c[-6:],'?')]+=1
            if b[5]<=round(b[6]*(1-L),2)+0.02 and b[5]/b[6]-1<=-(L-0.004): dtc[b[1]]+=1
    nav=CAP; cash=CAP; pos={}  # code-> dict(lane,shares,buy,entry_date)
    trades=[]; ranges={}
    tdays=[d for d in days if m0<=d<=m1]
    for di,d in enumerate(tdays):
        gi=days.index(d)
        if gi<22: continue
        d1=days[gi-1]; d2=days[gi-2]
        # ---- 先处理持仓卖出(T日) ----
        for c in list(pos):
            p=pos[c]; bars=by[c]; i=idx[c].get(d)
            if i is None: continue
            b=bars[i]; L=limp(c,b[10]); lim=round(b[6]*(1+L),2)
            sell=None; why=None
            if p['lane']=='B': sell=b[2]*(1-SLIP_SELL); why='B次日开盘'
            else:
                if b[5]<p['buy']*0.94: sell=b[5]*(1-SLIP_SELL); why='A止损-6%'
                elif not is_lim(b[5],b[6],L): sell=b[5]*(1-SLIP_SELL); why='A断板'
                elif d==tdays[-1]: sell=b[5]*(1-SLIP_SELL); why='A月末'
            if sell:
                sa=p['shares']*sell; ba=p['shares']*p['buy']; net=(sa-fee(sa,True)-ba-fee(ba,False))
                cash+=sa-fee(sa,True); trades.append(dict(code=c,lane=p['lane'],buy_date=p['entry'],sell_date=d,buy=p['buy'],sell=sell,net_pct=net/ba*100,why=why,sealed=p.get('sealed'))); del pos[c]
        # ---- T-1收盘生成范围单 ----
        cand=[]
        for c,bars in by.items():
            i=idx[c].get(d1)
            if i is None or i<21: continue
            b=bars[i]
            if b[10] or c[3]=='4' or c[3:5] in ('83','87','88','43','92'): continue
            chg=(b[5]/b[6]-1)*100
            if chg<3 or b[9]>10 or b[9]<=0: continue
            mc=b[8]/(b[9]/100) if b[9] else 0   # 流通市值近似=成交额/换手
            if not (10e8<=mc<=300e8): continue
            g20=(b[5]/bars[i-20][5]-1)*100
            if g20<10: continue
            L=limp(c,b[10]); board=is_lim(b[5],b[6],L)
            main=ztind[d1][IND.get(c[-6:],'?')]>=2
            if not (board or main): continue
            cand.append((0 if board else 1, b[9], c, board))
        cand.sort(); rng=[(c,board) for _,_,c,board in cand[:RANGE_N]]; ranges[d]=[c for c,_ in rng]
        # ---- 门 ----
        slots=SLOTS
        if ztc[d1]<50 and dtc[d1]>5: slots=1
        a_on = ztc[d1]>=ztc[d2]
        free=slots-len(pos)
        if free<=0 or not rng: continue
        # ---- T日分道 ----
        picks=[]
        for c,board in rng:
            i=idx[c].get(d); 
            if i is None or c in pos: continue
            b=by[c][i]; L=limp(c,b[10]); lim=round(b[6]*(1+L),2); gap=(b[2]/b[6]-1)*100
            trig=b[6]*(1+(0.17 if L>0.1 else 0.085))
            if gap<=0 and board and a_on: picks.append(dict(code=c,lane='A',price=b[2]*(1+SLIP_OPENBUY),sealed=None))
            elif 0<gap<=5:
                if touched(b[3],b[6],L):   # 触板=成交(挂涨停价)
                    picks.append(dict(code=c,lane='B',price=lim,sealed=is_lim(b[5],b[6],L)))
                # 到8.5%但没触板 → 未成交
        for p in picks[:free]:
            alloc=nav/SLOTS; sh=int(alloc/p['price']/100)*100
            if sh<=0: continue
            ba=sh*p['price']; 
            if cash<ba+fee(ba,False): continue
            cash-=ba+fee(ba,False); pos[p['code']]=dict(lane=p['lane'],shares=sh,buy=p['price'],entry=d,sealed=p['sealed'])
        # ---- 日终净值 ----
        mv=0
        for c,p in pos.items():
            i=idx[c].get(d); mv+=p['shares']*(by[c][i][5] if i is not None else p['buy'])
        nav=cash+mv
    # 月末强平未平仓(按最后收盘)
    for c,p in list(pos.items()):
        b=by[c][idx[c][tdays[-1]]]; sell=b[5]*(1-SLIP_SELL); sa=p['shares']*sell; ba=p['shares']*p['buy']
        trades.append(dict(code=c,lane=p['lane'],buy_date=p['entry'],sell_date=tdays[-1],buy=p['buy'],sell=sell,net_pct=(sa-fee(sa,True)-ba-fee(ba,False))/ba*100,why='期末强平',sealed=p.get('sealed')))
        cash+=sa-fee(sa,True); del pos[c]
    nav=cash
    return nav/CAP,trades,ranges
if __name__=='__main__':
    db,m0,m1=sys.argv[1:4]; nav,tr,rg=run(db,m0,m1)
    A=[t for t in tr if t['lane']=='A']; Bt=[t for t in tr if t['lane']=='B']; bz=[t for t in Bt if t['sealed'] is False]
    def s(x): n=[t['net_pct'] for t in x]; return f"{len(n)}笔/胜率{(sum(1 for v in n if v>0)/len(n)*100 if n else 0):.0f}%/均{(st.mean(n) if n else 0):+.2f}%"
    print(f"AB真人 {m0[:7]}~{m1[:7]}: NAV={nav:.4f} {(nav-1)*100:+.1f}% | A {s(A)} | B {s(Bt)} (其中炸板未封{len(bz)}笔 均{(st.mean([t['net_pct'] for t in bz]) if bz else 0):+.2f}%) | 范围单均{st.mean([len(v) for v in rg.values()]) if rg else 0:.1f}只/日")
    json.dump(dict(nav=nav,trades=tr,ranges=rg),open(f'ab_human_{m0[:7]}_{m1[:7]}.json','w'),ensure_ascii=False)
