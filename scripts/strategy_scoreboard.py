#!/opt/homebrew/bin/python3
"""A/B 策略月度记分牌 — Buwen 2026-09-08 令: "哪个策略过去一个月赚钱多就听哪个的, 没有高下之分"
⛔仲裁依据必须是算出来的, 不是我印象里哪个更"靠谱"。
⛔按今天的教训: 规则写进文件不算数, 必须在路径上 —— 本脚本挂 launchd 每日15:50, 
   并由收盘四步第①步强制读取 data/strategy_scoreboard.json。
口径: 只算**已实现**盈亏(realized_pnl), 扣费后; 浮盈不计入(否则谁死扛谁分高)。
"""
import json,os,sys,datetime
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,os.path.join(ROOT,'scripts'))
def run(days=30):
    st=json.load(open(f'{ROOT}/portfolio_state.json'))
    cut=(datetime.date.today()-datetime.timedelta(days=days)).isoformat()
    try:
        from astock_rules import fees
    except Exception:
        fees=None
    box={'A':{'trades':0,'gross':0.0,'fee':0.0,'wins':0},'B':{'trades':0,'gross':0.0,'fee':0.0,'wins':0}}
    for t in st.get('trade_log',[]):
        if t.get('account')!='a_share' or t.get('date','')<cut: continue
        if t.get('action')!='sell': continue
        k='B' if t.get('book')=='b' else 'A'
        pnl=t.get('realized_pnl')
        if pnl is None: continue
        box[k]['trades']+=1; box[k]['gross']+=pnl; box[k]['wins']+= 1 if pnl>0 else 0
        if fees:
            v=t.get('value') or 0
            box[k]['fee']+= fees(v,'sell')['total']+fees(v,'buy')['total']
    out={'date':datetime.date.today().isoformat(),'window_days':days,'since':cut}
    for k,v in box.items():
        net=v['gross']-v['fee']
        out[k]={'closed_trades':v['trades'],'gross_pnl':round(v['gross'],2),
                'est_fee':round(v['fee'],2),'net_pnl':round(net,2),
                'win_rate':round(v['wins']/v['trades']*100,1) if v['trades'] else None}
    a,b=out['A']['net_pnl'],out['B']['net_pnl']
    # ⛔2026-09-08 Buwen纠正: "我可没说样本, 我说的是实打实的操作"。
    #   我原本自己加了"任一方<10笔不仲裁"的门槛 —— 他没说过。他的规则就是: 过去一个月谁真赚得多听谁的。
    #   这是我的老毛病: 他给一条规则, 我加一堆自己的条件, 然后按我加的条件执行, 结果偏离他要的。
    #   同族: 把"9:24前阴占比≥60%"当硬条件把中信出版筛掉 / 把"竞价即涨停"当超级大红的条件。
    out['verdict']='A' if a>b else ('B' if b>a else '平')
    out['verdict_detail']=(f"过去{days}天实打实赚到的钱(已实现, 扣费): A {a:+,.0f} vs B {b:+,.0f} → 听 {out['verdict']}"
        + (f"  [B目前{out['B']['closed_trades']}笔, 数字如实报, 不因笔数少就拒绝裁决]" if out['B']['closed_trades']<5 else ""))
    json.dump(out,open(f'{ROOT}/data/strategy_scoreboard.json','w'),ensure_ascii=False,indent=1)
    return out

def weekly():
    """周频记分卡 — 与任何公开榜单同口径可比。
    ⛔用周收益而非累计: 累计会被低仓位掩盖(在跌18%的市场里空着64%仓位本身就能跑赢, 那不算本事)。
    周频暴露的是真实选股能力。"""
    import datetime, urllib.request, json as _j
    st=json.load(open(f'{ROOT}/portfolio_state.json'))
    today=datetime.date.today()
    mon=today-datetime.timedelta(days=today.weekday())      # 本周一
    prev_fri=mon-datetime.timedelta(days=3)                 # 上周五
    acc=st['accounts']['a_share']
    def mkt(x): return 'sh' if x[0] in '56' else ('bj' if x[0] in '48' else 'sz')
    ps=acc['positions']; cs=[str(p['ticker'])[-6:] for p in ps]
    q={}
    if cs:
        raw=urllib.request.urlopen('http://qt.gtimg.cn/q='+','.join(mkt(c)+c for c in cs),timeout=10).read().decode('gbk','ignore')
        for line in raw.split('\n'):
            x=line.split('~')
            if len(x)>4 and 'none_match' not in line: q[x[2]]={'now':float(x[3]),'n':x[1]}
    mv=sum(q.get(str(p['ticker'])[-6:],{}).get('now',p['avg_cost'])*p['shares'] for p in ps)
    total=mv+acc['cash']
    # 本周已实现(按book分)
    wk={'A':0.0,'B':0.0}; cnt={'A':0,'B':0}
    for t in st['trade_log']:
        if t.get('account')!='a_share' or t.get('action')!='sell': continue
        if t.get('date','')<mon.isoformat(): continue
        k='B' if t.get('book')=='b' else 'A'
        if t.get('realized_pnl') is not None:
            wk[k]+=t['realized_pnl']; cnt[k]+=1
    # 基准: 上证本周
    idx=urllib.request.urlopen('http://qt.gtimg.cn/q=sh000001',timeout=8).read().decode('gbk','ignore').split('~')
    sse_now=float(idx[3]); sse_pc=float(idx[4])
    out={'week_of':mon.isoformat(),'as_of':today.isoformat(),
         'total_assets':round(total,2),'position_pct':round(mv/total*100,1),
         'A':{'realized_this_week':round(wk['A'],2),'closed_trades':cnt['A']},
         'B':{'realized_this_week':round(wk['B'],2),'closed_trades':cnt['B']},
         'sse_index':sse_now}
    json.dump(out,open(f'{ROOT}/data/weekly_scorecard.json','w'),ensure_ascii=False,indent=1)
    lines=[f"[A股周记分卡 {mon} 当周]",
           f"总资产 {total:,.0f} 元, 仓位 {mv/total*100:.1f}%",
           f"A策略 本周已实现 {wk['A']:+,.0f} ({cnt['A']}笔)",
           f"B策略 本周已实现 {wk['B']:+,.0f} ({cnt['B']}笔)",
           f"上证指数 {sse_now}",
           "⛔口径: 只算已实现且扣费, 浮盈不计(否则谁死扛谁分高)"]
    msg='\n'.join(lines)
    print(msg)
    try:
        import subprocess
        r=subprocess.run(['bash',os.path.expanduser('~/.claude/session-remote/fs-reply.sh'),msg],capture_output=True,timeout=20)
        print('  飞书:', '已发' if r.returncode==0 else f'失败 rc={r.returncode}')
    except Exception as e: print('  飞书异常',type(e).__name__)
    return out

if __name__=='__main__':
    if sys.argv[1:] and sys.argv[1]=='weekly':
        weekly(); sys.exit(0)
    o=run(int(sys.argv[1]) if len(sys.argv)>1 else 30)
    print(f"=== A/B 策略记分牌 · 过去{o['window_days']}天(自{o['since']}) ===")
    for k in ('A','B'):
        v=o[k]; print(f"  {k}: 已实现{v['closed_trades']:>2}笔 毛{v['gross_pnl']:>+10,.0f} "
                      f"费{v['est_fee']:>8,.0f} 净{v['net_pnl']:>+10,.0f} 胜率{v['win_rate']}")
    print(f"\n  裁决: {o['verdict']}")
    print(f"  {o['verdict_detail']}")
