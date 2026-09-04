#!/opt/homebrew/bin/python3
"""逐笔diff: 对比两个引擎(或同引擎不同参数)在同一区间产出的交易明细。

⛔为什么要有这个(2026-09-04教训, research2经由main提出):
今天我把"脚本传错参数"的效果误判成"bug修复效果", 因为我只比了月度总收益(+99.8% vs +122%)。
若当时有逐笔diff, 会立刻看到**持仓集合完全不同**(入场日/标的都变了), 一眼就知道不是修复效果。
月度总收益是聚合量, 聚合会把"哪些笔变了"的信息抹掉; 逐笔diff把它还原出来。

输出 old/new/why 三列风格的CSV, 每笔一行, 分四类:
  ONLY_OLD  只在旧版出现的交易(被新口径剔除)
  ONLY_NEW  只在新版出现的交易(被新口径新增)
  CHANGED   同一(标的,入场日)但价格/出场/收益变了
  SAME      完全一致

用法: trade_diff.py <db> <m0> <m1> [out.csv]
"""
import sys,csv
B='/Users/huaichuaibeimeng/claude-projects/sim-portfolio/backtest/2026-08-24-daban/'
sys.path.insert(0,B)
import engine, engine_fix

def run_one(mod,db,m0,m1):
    by=mod.load(B+db); sig=mod.signals(by,m0,m1)
    TD=sorted({b[1] for bars in by.values() for b in bars if m0<=b[1]<=m1})
    if not TD: return {},0
    nav,tr,_=mod.run(by,sig,TD,TD[-1])
    out={}
    for t in tr:
        k=(t.get('code'), t.get('buy_date') or t.get('d') or t.get('date'))
        out[k]=t
    return out,nav

def main():
    db,m0,m1=sys.argv[1:4]
    outp=sys.argv[4] if len(sys.argv)>4 else f'/tmp/trade_diff_{m0[:7]}.csv'
    old,nav_o=run_one(engine,db,m0,m1)
    new,nav_n=run_one(engine_fix,db,m0,m1)
    keys=sorted(set(old)|set(new), key=lambda k:(str(k[1]),str(k[0])))
    rows=[]; cnt={'ONLY_OLD':0,'ONLY_NEW':0,'CHANGED':0,'SAME':0}
    for k in keys:
        o=old.get(k); n=new.get(k)
        if o and not n: cls='ONLY_OLD'
        elif n and not o: cls='ONLY_NEW'
        else:
            cls='SAME' if abs((o.get('net',0))-(n.get('net',0)))<1e-9 else 'CHANGED'
        cnt[cls]+=1
        rows.append({'class':cls,'code':k[0],'buy_date':k[1],
            'old_net':round(o.get('net',0),4) if o else '',
            'new_net':round(n.get('net',0),4) if n else '',
            'old_buy':o.get('buy','') if o else '', 'new_buy':n.get('buy','') if n else '',
            'old_sell':o.get('sell','') if o else '','new_sell':n.get('sell','') if n else '',
            'why':{'ONLY_OLD':'旧口径识别为板,新口径不认','ONLY_NEW':'新口径新识别出的板',
                   'CHANGED':'同一笔但价格/出场变化','SAME':''}[cls]})
    with open(outp,'w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    print(f"{m0[:7]}  旧NAV={nav_o:.4f}  新NAV={nav_n:.4f}")
    print(f"  逐笔: SAME {cnt['SAME']} | CHANGED {cnt['CHANGED']} | ONLY_OLD {cnt['ONLY_OLD']} | ONLY_NEW {cnt['ONLY_NEW']}")
    tot=sum(cnt.values())
    same_pct=cnt['SAME']/tot*100 if tot else 0
    print(f"  → 持仓集合重合度 {same_pct:.0f}%")
    if same_pct<50:
        print("  ⛔警告: 重合度<50%, 这不像'同一策略的口径微调', 更像参数/逻辑被改动。先查参数再解读收益差。")
    print(f"  明细: {outp}")

if __name__=='__main__': main()
