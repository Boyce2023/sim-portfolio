#!/opt/homebrew/bin/python3
"""⛔待裁决台账 — 治"我在交易理由里承诺了某天复核, 然后忘了"。

起因(2026-09-07): 我08-24减半概伦电子时写明"保留一半等08-27中报裁决",
中报披露11天后才发现**那次裁决从未执行**。回扫trade_log发现类似承诺共55条,
它们只存在于reason的一段文本里, 没有任何机制会在到期日提醒我。
⛔漏做比做错更危险: 做错留下痕迹能复盘, 漏做是静默的。

用法:
  pending_verdicts.py add <ticker> <due_date> <条件> [--source trade_id]   登记
  pending_verdicts.py intel <id> <情报内容>                          追加情报(写完读回验证)
  pending_verdicts.py list [--due]                                        列出(--due只列到期)
  pending_verdicts.py done <id> <结论>                                     结案
台账: data/pending_verdicts.json
每日16:00收盘版四步的第①步必须调用 list --due, 有到期项先处理再往下走。
"""
import json,sys,os,datetime
P=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),'data','pending_verdicts.json')
def load():
    if not os.path.exists(P): return {"items":[]}
    return json.load(open(P))
def save(d): json.dump(d,open(P,'w'),ensure_ascii=False,indent=1)
def today(): return datetime.date.today().isoformat()
def main():
    a=sys.argv[1:] or ['list']
    d=load()
    if a[0]=='add':
        tk,due,cond=a[1],a[2],' '.join(a[3:])
        nid=max([x['id'] for x in d['items']],default=0)+1
        d['items'].append({"id":nid,"ticker":tk,"due":due,"condition":cond,
                           "created":today(),"status":"open","verdict":None,"closed":None})
        save(d); print(f"[+] #{nid} {tk} due={due}: {cond}")
    elif a[0]=='intel':
        # ⛔2026-09-12新增: 此前没有写 intel_log 的入口, 每次记情报都靠临时脚本,
        #   而临时脚本我用错了字段名(i.get('code') 而台账字段是 ticker), 循环体一次没进,
        #   print 却在循环外照样输出"已记录" —— 静默零写入, 还在同一句话里报告给了 Buwen。
        #   根因是工具缺口不是手滑, 故补此子命令: 匹配为空即非零退出, 写完读回验证。
        i=int(a[1]); note=' '.join(a[2:])
        if not note: sys.exit("⛔ intel 内容为空, 拒绝写入")
        hit=[x for x in d['items'] if x['id']==i]
        if not hit: sys.exit(f"⛔ 未找到 #{i}, 零写入(不静默通过)")
        x=hit[0]
        x.setdefault('intel_log',[]).append({"date":today(),"note":note})
        n_want=len(x['intel_log'])
        save(d)
        chk=[y for y in json.load(open(P))['items'] if y['id']==i][0].get('intel_log') or []
        if len(chk)!=n_want: sys.exit(f"⛔ 写入校验失败: 期望{n_want}条实得{len(chk)}条")
        print(f"[i] #{i} {x['ticker']} intel_log 现{len(chk)}条(已读回验证): {note[:70]}")
    elif a[0]=='done':
        i=int(a[1]); v=' '.join(a[2:])
        for x in d['items']:
            if x['id']==i:
                x['status']='closed'; x['verdict']=v; x['closed']=today()
                save(d); print(f"[✓] #{i} {x['ticker']} 结案: {v[:80]}"); return
        sys.exit(f"未找到 #{i}")
    else:
        only_due='--due' in a
        op=[x for x in d['items'] if x['status']=='open']
        if only_due: op=[x for x in op if x['due']<=today()]
        if not op:
            print("（无到期待裁决）" if only_due else "（无未结项）"); return
        print(f"{'到期' if only_due else '全部'}待裁决 {len(op)} 项:")
        # ⛔2026-09-17修: 原行直接下标 x['ticker'] / x['condition'], 撞上非add建的条目即 KeyError 崩溃。
        #   实况: 台账并存两套字段名 —— add命令建的47条用 ticker/condition, 另有2条(#28/#29,
        #   09-09与09-10由别的路径塞入)用 code/name/rule。两条due都在10月以后, 所以 list --due
        #   永远列不到, 而全量 list 一跑就崩、崩了就没人再跑 —— 缺陷因此长期不可见。
        #   ⛔修法刻意不做静默兼容: 非标准字段的条目照常列出但打⛔标记, 真正残缺的单独吵一行,
        #   否则只是把"崩溃"换成"看起来正常", 那比崩溃更糟(故障必须吵, 不得降级成合法正常值)。
        n_alt=0
        for x in sorted(op,key=lambda y:y['due']):
            flag='⛔已到期' if x['due']<=today() else '  '
            tk=x.get('ticker') or x.get('code')
            cond=x.get('condition') or x.get('rule')
            if not tk or not cond:
                print(f" ⛔残缺 #{x['id']} due={x.get('due')} 既无ticker/condition也无code/rule, 键={list(x.keys())}")
                n_alt+=1; continue
            alt=''
            if not ('ticker' in x and 'condition' in x):
                alt=' ⛔[非标准字段·用的是code/rule, add命令建不出这种形态]'; n_alt+=1
            print(f" {flag} #{x['id']} {tk} due={x['due']}{alt} :: {cond[:90]}")
        if n_alt:
            print(f"\n⛔ 上列有 {n_alt} 条非标准/残缺条目 —— 它们不是add命令建的, 修字段名或重建前不要假设下游脚本读得到。")
if __name__=='__main__': main()
