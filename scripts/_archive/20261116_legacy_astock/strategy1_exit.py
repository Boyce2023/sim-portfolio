#!/opt/homebrew/bin/python3.13
"""策略一自动卖出(2026-10-08 建, Buwen: "T+5你就要完全遵守啊, 不然我给你策略干嘛")
每个交易日 14:55 跑: A股非B专户持仓, ①持有满4个交易日(买入日为T, 第4个交易日)即卖(2026-10-13 由T+5改T+4) ②现价跌破买价7%即卖(收盘判定, 14:55近似)。
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
    # ⛔2026-11-13 策略物理隔离硬锁: 由黑名单改为严格白名单!
    # 仅认领显式标记为基本面短线(strategy_id=='s_fund' 或遗留无strategy_id且reason以[策略一]/策略一开头)的持仓,
    # 严禁触碰一进二(s_1to2)、三进四(s_3to4)、高标(s_high_rebound/s_high_5ban)及冰点撬板(s_pry)任何持仓!
    def _is_strategy1(c, t):
        p = pos[c]
        sid = p.get('strategy_id')
        if sid is not None:
            return sid == 's_fund'
        if p.get('book') in ('b', 'quant_4bucket', 's_1to2', 's_3to4', 's_high_rebound', 's_high_5ban', 's_pry'):
            return False
        rsn = str(t.get('reason') or '').strip()
        return rsn.startswith(('[策略一]', '策略一'))
    todo=[c for c,t in last.items() if _is_strategy1(c, t)]
    if not todo: print('无策略一持仓'); return
    q=A.get_batch_prices(todo); done=[]
    for c in todo:
        t=last[c]; px=(q.get(c) or {}).get('price'); cost=float(pos[c].get('avg_cost') or t.get('price'))
        if not px: fs(f'[astock⛔] 策略一卖出检查: {c} 取不到价, 本轮未处理'); continue
        n=tdays_between(datetime.date.fromisoformat(str(t['date'])[:10]),today,closed)
        why=None
        if n>=4: why=f'T+{n} 到期'   # 2026-10-13 Buwen 令由 T+5 改为 T+4
        elif px<=cost*0.93: why=f'现价{px}跌破买价{cost}的7%'
        if not why: print(f'{c} T+{n} 现价{px} 持有'); continue
        r=subprocess.run(['/opt/homebrew/bin/python3.13',f'{ROOT}/scripts/execute_trade.py','sell','--account','cn','--ticker',c,'--all',
                          '--strategy-id','s_fund',
                          '--reason',f'策略一规则自动卖出(strategy1_exit): {why}。买入日 {str(t["date"])[:10]} 价 {cost}。'],
                          capture_output=True,text=True,cwd=ROOT)
        print(f'{c} T+{n} 现价{px} 卖出: {why} -> {"成交" if "[OK]" in r.stdout else "失败"}')
        if '[OK]' in r.stdout: done.append(f'{c} {why} @{px}')
        else: fs(f'[astock⛔] 策略一卖出失败 {c}: {(r.stderr or r.stdout).strip()[-200:]}')
    if done: fs('[astock] 策略一规则卖出:\n'+'\n'.join(done))
if __name__=='__main__': main()
