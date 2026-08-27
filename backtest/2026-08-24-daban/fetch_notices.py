#!/usr/bin/env python3
"""抓全市场历史公告 → SQLite。用于B策略消息回测。

⛔PIT纪律: 公告日期T的公告可能是T日盘后发布的(与铁律1的盘前/盘后问题同源),
   因此下游只允许用 公告日期 <= T-1 的记录去预测T日的打板结果。本脚本只负责如实入库。
⛔自带心跳: 每处理一天写.hb_notice,防止卡死无感知(20分钟无进展铁律)。
"""
import sqlite3, sys, time, datetime, signal, warnings
warnings.filterwarnings('ignore')
import akshare as ak

DB = 'notices.db'
HB = '.hb_notice'

class TO(Exception): pass
def _alarm(s, f): raise TO()
signal.signal(signal.SIGALRM, _alarm)

def trading_days(db, start, end):
    c = sqlite3.connect(db)
    r = [x[0] for x in c.execute("select distinct date from k where date>=? and date<=? order by date", (start, end))]
    c.close(); return r

def main():
    src, start, end = sys.argv[1], sys.argv[2], sys.argv[3]
    days = trading_days(src, start, end)
    con = sqlite3.connect(DB)
    con.execute("""create table if not exists notice(
        code text, name text, title text, ntype text, ndate text)""")
    con.execute("create index if not exists ix_nd on notice(ndate)")
    con.execute("create index if not exists ix_nc on notice(code,ndate)")
    con.execute("create table if not exists done(d text primary key, n int)")
    con.commit()
    have = {x[0] for x in con.execute("select d from done")}
    todo = [d for d in days if d not in have]
    print(f'[notice] {src} {start}~{end}: 交易日{len(days)} 已抓{len(have)} 待抓{len(todo)}', flush=True)
    ok = fail = 0
    for i, d in enumerate(todo):
        ds = d.replace('-', '')
        got = 0
        for attempt in range(3):
            try:
                signal.alarm(150)  # ⛔2026-08-27修: 财报季高峰日1万+条公告要40秒+,25秒把公告最多的日子系统性掐死(缺的55天全是年报/三季报季)
                df = ak.stock_notice_report(symbol="全部", date=ds)
                signal.alarm(0)
                rows = [(str(r['代码']).zfill(6), r['名称'], r['公告标题'], r['公告类型'],
                         str(r['公告日期'])[:10]) for _, r in df.iterrows()]
                con.executemany("insert into notice values(?,?,?,?,?)", rows)
                con.execute("insert or replace into done values(?,?)", (d, len(rows)))
                con.commit(); got = len(rows); ok += 1
                break
            except TO:
                signal.alarm(0)
                # ⛔2026-08-27修: 原来超时三次用完直接跳出,fail计数器没加,
                #   结果12天被静默吞掉而心跳显示"处理了"、fail=0。
                #   与D6死代码/行业映射86%空同族: 失败必须计数,否则"看起来跑完了"。
                if attempt == 2:
                    fail += 1
                    print(f'[notice] {d} TIMEOUT×3 放弃', flush=True)
                time.sleep(2)
            except Exception as e:
                signal.alarm(0)
                if attempt == 2:
                    fail += 1
                    print(f'[notice] {d} FAIL {str(e)[:60]}', flush=True)
                time.sleep(2)
        open(HB, 'w').write(f'{datetime.datetime.now():%H:%M:%S} {i+1}/{len(todo)} {d} rows={got} ok={ok} fail={fail}\n')
        if (i + 1) % 20 == 0:
            print(f'[notice] {i+1}/{len(todo)} 最新{d} ok={ok} fail={fail} 库存={con.execute("select count(*) from notice").fetchone()[0]}', flush=True)
    print(f'[notice] DONE ok={ok} fail={fail} 总记录={con.execute("select count(*) from notice").fetchone()[0]}', flush=True)
    con.close()

main()
