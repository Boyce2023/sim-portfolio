#!/opt/homebrew/bin/python3.13
"""Buwen 日度复盘的吸收台账: 列出桌面「日度复盘」里新出现或改过、还没吸收进 strategy_astock.md 的文件。

2026-09-22 建。Buwen 原话「你现在再读一下我在那之后的各类日度复盘，然后把你学到的都融入你的策略……以后日度补充」。
只读他的目录, 不写、不改、不移动他的任何文件; 台账放在 sim-portfolio/data/review_ingest.json。

用法:
  python3.13 scripts/review_ingest.py            # 列出待吸收(收盘四步第①步调用)
  python3.13 scripts/review_ingest.py --text     # 同时打印待吸收文件的全文
  python3.13 scripts/review_ingest.py --done 0922复盘.docx "吸收了什么, 写进了纲领哪一节"
"""
import os, sys, json, subprocess, datetime as dt

DIR = os.path.expanduser("~/Desktop/日度复盘")
LEDGER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "review_ingest.json")


def load():
    return json.load(open(LEDGER, encoding="utf-8")) if os.path.exists(LEDGER) else {}


def text(path):
    r = subprocess.run(["textutil", "-convert", "txt", "-stdout", path], capture_output=True, text=True)
    return r.stdout


def pending():
    led = load()
    out = []
    for fn in sorted(os.listdir(DIR)):
        if not fn.endswith(".docx") or fn.startswith("~$"):
            continue
        p = os.path.join(DIR, fn)
        mt = os.path.getmtime(p)
        rec = led.get(fn)
        if rec is None or mt > rec["mtime"] + 1:
            out.append((fn, p, mt, "新文件" if rec is None else "吸收后又改过"))
    return out


def main():
    a = sys.argv[1:]
    if a and a[0] == "--done":
        fn, note = a[1], " ".join(a[2:])
        if not note:
            sys.exit("⛔ --done 必须写明吸收了什么")
        p = os.path.join(DIR, fn)
        if not os.path.exists(p):
            sys.exit(f"⛔ 找不到 {p}")
        led = load()
        led[fn] = {"mtime": os.path.getmtime(p), "ingested_at": dt.datetime.now().isoformat(timespec="seconds"), "note": note}
        json.dump(led, open(LEDGER, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        chk = load()
        print(f"[✓] {fn} 已记为吸收(读回 {'✓' if fn in chk else '⛔'})")
        return
    pend = pending()
    total = len([f for f in os.listdir(DIR) if f.endswith('.docx') and not f.startswith('~$')])
    print(f"[review_ingest] 目录共 {total} 份复盘, 待吸收 {len(pend)} 份")
    for fn, p, mt, why in pend:
        print(f"  ⛔ {fn}  ({why}, 修改于 {dt.datetime.fromtimestamp(mt):%m-%d %H:%M})")
        if "--text" in a:
            print(text(p))
            print("-" * 60)


if __name__ == "__main__":
    main()
