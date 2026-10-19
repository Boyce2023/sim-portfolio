#!/opt/homebrew/bin/python3
"""开盘啦 异动提醒数据每日存档(2026-10-19 建, Buwen: "有办法长期弄他的数据接口吧")
接口是开盘啦 App 自用的, 未公开, 随时可能改版或加签名; 所以每天落一份本地档, 接口哪天断了历史也不丢。

存什么(data/kpl/):
  severe_his.json      严重异动历史, 增量合并(键=代码+异动日期+触发条件), 永不删旧行
  pianlizhi/YYYYMMDD_HHMM.json   今日"涨到涨停就会触发严重异动"的临界名单, 盘中多次快照
  zdjk/YYYYMMDD.json   重点监控当日名单
用法: python3 scripts/kpl_archive.py [his|pianlizhi|all]   (launchd: 09:45/14:40 跑 pianlizhi, 15:25 跑 all)
⛔ 接口返回空或 errcode 不是 0, 一律飞书报警并非零退出, 不当成"今天没有异动"。"""
import json, os, sys, time, gzip, zlib, datetime, subprocess, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data', 'kpl')
BASE = {'PhoneOSNew': 2, 'UserID': 0, 'VerSion': '6.2.30.2', 'apiv': 'w47'}   # App 升级后若接口失效, 先改这里的版本号


def alert(msg):
    print(msg, flush=True)
    try:
        subprocess.run(['bash', os.path.expanduser('~/.claude/session-remote/fs-reply.sh'), f'[astock⛔] {msg}'],
                       capture_output=True, timeout=20)
    except Exception:
        pass


def get(host, params):
    q = '&'.join(f'{k}={v}' for k, v in {**BASE, **params}.items())
    req = urllib.request.Request(f'https://{host}.kaipanla.com/w1/api/index.php?{q}', headers={'User-Agent': 'kpl/6.2.30.2'})
    raw = urllib.request.urlopen(req, timeout=20).read()
    for f in (gzip.decompress, zlib.decompress, lambda b: zlib.decompress(b, -15), lambda b: b):
        try:
            txt = f(raw).decode('utf-8')
            break
        except Exception:
            txt = ''
    if not txt.strip():
        raise RuntimeError(f'{params.get("a")} 返回空')
    d = json.loads(txt)
    if str(d.get('errcode', '0')) != '0':
        raise RuntimeError(f'{params.get("a")} errcode={d.get("errcode")} {d.get("errmsg", "")}')
    return d


def his():
    p = os.path.join(OUT, 'severe_his.json')
    old = json.load(open(p)) if os.path.exists(p) else {'rows': []}
    key = lambda r: (r[0], r[18], r[2])
    seen = {key(r) for r in old['rows']}
    new, idx, total = [], 0, None
    while True:
        d = get('apphis', {'c': 'StockBidYiDong', 'a': 'GetYDTPZFPL_W46_HisAll', 'Index': idx})
        L = d.get('List_His') or []
        total = d.get('List_His_Total')
        fresh = [r for r in L if key(r) not in seen]
        new += fresh
        idx += len(L)
        # 首次全量; 之后翻到整页都是旧记录就停
        if not L or (old['rows'] and not fresh) or (total and idx >= int(total)):
            break
        time.sleep(0.6)
    rows = new + old['rows']
    rows.sort(key=lambda r: r[18], reverse=True)
    json.dump({'total_api': total, 'updated': datetime.datetime.now().isoformat(timespec='seconds'), 'rows': rows},
              open(p, 'w'), ensure_ascii=False)
    print(f'严重异动历史: 新增 {len(new)} 条, 本地共 {len(rows)} 条, 接口总数 {total}')


def pianlizhi():
    d = get('apphwhq', {'c': 'StockBidYiDong', 'a': 'GetPianLiZhi_W46'})
    os.makedirs(os.path.join(OUT, 'pianlizhi'), exist_ok=True)
    fn = datetime.datetime.now().strftime('%Y%m%d_%H%M') + '.json'
    json.dump(d, open(os.path.join(OUT, 'pianlizhi', fn), 'w'), ensure_ascii=False)
    print(f'临界名单 {fn}: 今日 {len(d.get("List_Today") or [])} 只, 明日 {len(d.get("List_Tormorow") or [])} 只')


def zdjk():
    d = get('apphwhq', {'c': 'StockBidYiDong', 'a': 'GetYDTP_ZDJK_Today'})
    os.makedirs(os.path.join(OUT, 'zdjk'), exist_ok=True)
    json.dump(d, open(os.path.join(OUT, 'zdjk', datetime.date.today().strftime('%Y%m%d') + '.json'), 'w'), ensure_ascii=False)
    print(f'重点监控 {len(d.get("List") or [])} 只')


def main():
    if datetime.date.today().weekday() >= 5:
        print('周末跳过'); return 0
    os.makedirs(OUT, exist_ok=True)
    what = sys.argv[1] if len(sys.argv) > 1 else 'all'
    jobs = {'his': [his], 'pianlizhi': [pianlizhi], 'all': [his, pianlizhi, zdjk]}[what]
    bad = []
    for j in jobs:
        try:
            j()
        except Exception as e:
            bad.append(f'{j.__name__}: {type(e).__name__} {e}')
    if bad:
        alert('开盘啦存档失败(接口可能改版, 先查 BASE 里的版本号): ' + ' | '.join(bad))
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
