#!/opt/homebrew/bin/python3
"""策略一自动卖出(2026-10-08 建, Buwen: "T+5你就要完全遵守啊, 不然我给你策略干嘛")
每个交易日 14:55 跑: A股非B专户持仓, ①持有满5个交易日(买入日为T, 第5个交易日)即卖 ②现价跌破买价7%即卖(收盘判定, 14:55近似)。
此前 T+5 只写在文档和台账里, 靠我记得执行; 09-28/09-29 监听断了就漏, 后来我又自作主张只卖一半。下沉为定时任务后不再依赖记得。"""
import json,os,sys,datetime,subprocess
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0,f'{ROOT}/scripts')
def fs(m): subprocess.run(['bash',os.path.expanduser('~/.claude/session-remote/fs-reply.sh'),m],capture_output=True,timeout=20)
def tdays_between(d0,d1,closed):
    n=0; d=d0+datetime.timedelta(days=1)
    while d<=d1:
        if d.weekday()<5 and d.isoformat() not in closed: n+=1
        d+=datetime.timedelta(days=1)
    return n
def main():
    today=datetime.date.today()
    closed=set(json.load(open(f'{ROOT}/market_calendar.json'))['trading_days_by_market']['cn_closed_dates'])
    if today.weekday()>=5 or today.isoformat() in closed: print('非交易日'); return
    st=json.load(open(f'{ROOT}/portfolio_state.json'))
    pos={str(x.get('ticker'))[-6:]:x for x in (st['accounts']['a_share'].get('positions') or [])}
    last={}
    for t in st.get('trade_log') or []:
        c=str(t.get('ticker'))[-6:]
        if t.get('account') in ('cn','a_share') and t.get('action')=='buy' and c in pos: last[c]=t
    import astock_data_layer as A
    todo=[c for c,t in last.items() if 'B策略专户' not in str(t.get('reason') or '')]
    if not todo: print('无策略一持仓'); return
    q=A.get_batch_prices(todo); done=[]
    for c in todo:
        t=last[c]; px=(q.get(c) or {}).get('price'); cost=float(pos[c].get('avg_cost') or t.get('price'))
        if not px: fs(f'[astock⛔] 策略一卖出检查: {c} 取不到价, 本轮未处理'); continue
        n=tdays_between(datetime.date.fromisoformat(str(t['date'])[:10]),today,closed)
        why=None
        if n>=5: why=f'T+{n} 到期'
        elif px<=cost*0.93: why=f'现价{px}跌破买价{cost}的7%'
        if not why: print(f'{c} T+{n} 现价{px} 持有'); continue
        r=subprocess.run(['/opt/homebrew/bin/python3',f'{ROOT}/scripts/execute_trade.py','sell','--account','cn','--ticker',c,'--all',
                          '--reason',f'策略一规则自动卖出(strategy1_exit): {why}。买入日 {str(t["date"])[:10]} 价 {cost}。'],
                          capture_output=True,text=True,cwd=ROOT)
        if '[OK]' in r.stdout: done.append(f'{c} {why} @{px}')
        else: fs(f'[astock⛔] 策略一卖出失败 {c}: {(r.stderr or r.stdout).strip()[-200:]}')
    if done: fs('[astock] 策略一规则卖出:\n'+'\n'.join(done))
if __name__=='__main__': main()
