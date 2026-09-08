#!/opt/homebrew/bin/python3
"""任务台账写入器 — 统一字段名, 不靠"记得用 updated_at"
⛔2026-09-08 main 指出: 我的台账有20行写成 `ts` 而非协议规定的 `updated_at`。
   汇总脚本按 updated_at 字符串比大小挑每个 id 的最终态, **空字符串永远排最旧**
   → 用 ts 写的状态更新在 Buwen 的 Excel 里**静默不生效**(实测 research2 一条一直显示 doing 实际早已 done)。
   main 已加归一化兜底, 但源头不该再写错。字段名靠记 = 迟早再错, 所以做成脚本。
用法:
  log_task.py <theme> <detail> <status> [followup]
  log_task.py --id <既有id> --status done --detail "..."     更新既有任务
status: todo / doing / done / blocked
"""
import json,sys,datetime,os,argparse
LEDGER=os.path.expanduser('~/.claude/nexus/tasks/astock.jsonl')
def now(): return datetime.datetime.now().isoformat(timespec='seconds')
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('theme',nargs='?'); ap.add_argument('detail',nargs='?')
    ap.add_argument('status',nargs='?',default='done')
    ap.add_argument('followup',nargs='?',default='')
    ap.add_argument('--id'); ap.add_argument('--status',dest='st2'); ap.add_argument('--detail',dest='dt2')
    a=ap.parse_args()
    if a.id:
        row={"id":a.id,"updated_at":now(),"role":"astock"}
        if a.st2: row["status"]=a.st2
        if a.dt2: row["detail"]=a.dt2
    else:
        if not (a.theme and a.detail): print(__doc__); sys.exit(2)
        d=datetime.date.today().strftime('%Y%m%d')
        n=sum(1 for _ in open(LEDGER)) if os.path.exists(LEDGER) else 0
        row={"id":f"astock-{d}-{n+1}","updated_at":now(),"role":"astock",
             "theme":a.theme,"detail":a.detail,"status":a.status,"followup":a.followup}
    with open(LEDGER,'a') as f: f.write(json.dumps(row,ensure_ascii=False)+'\n')
    print(f"[+] {row.get('id')} {row.get('status','')} updated_at={row['updated_at']}")
if __name__=='__main__': main()
