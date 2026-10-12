#!/opt/homebrew/bin/python3.13
"""A股日线库每日追加 (data/cn_hk_price_db/a_daily.parquet)。

2026-09-22 建。起因: 该库 09-09 一次性建库到 09-08, 建库脚本放在 /tmp 已被清掉, 此后**从来没有每日追加的脚本**。
memory 记的"增量走 kline_cache.update_from_db"是反的, 那个函数只从本库读、不往本库写。
09-09 到 09-15 库里残留每天约 1792 行(九成是深市 002/000 段, adj_close 与 qfq_factor 全空), 是某次半截补数留下的。

做法:
  1. 找到最后一个"完整"交易日(当日行数 >= 基准日行数的 97%), 丢弃其后所有残行。
  2. 用 iFinD history 批量拉(60只一批)之后每个交易日的 OHLC/成交量/成交额/换手率/前收盘。
     单位已于 2026-09-22 对 688758/600519/000001 在 09-08 逐字段核对: volume=股, amount=元, turnoverRatio=百分数(除以100入库)。
  3. 除权识别: 前收盘 / 库内上一收盘 偏离超过 0.1% 视为除权除息, 该股此前全部行 qfq_factor /= r
     (A股 前复权 adj_close = close / qfq_factor, 最新因子为 1)。
  4. oshare 沿用该股库内最后一个值。
  5. 校验: 每个新日期行数 >= 基准 97%, close 无空值; 抽样与腾讯日K比对收盘价。
  6. 写临时文件, 校验通过再原子替换, 原文件备份为 a_daily.parquet.bak。

用法:
  DRY_RUN=1 python3.13 scripts/cn_price_db_update.py        # 只拉数与校验, 不写库
  python3.13 scripts/cn_price_db_update.py                  # 真写
  END=2026-09-21 python3.13 scripts/cn_price_db_update.py   # 指定截止日
⛔ 15:30 之前运行时截止日自动取前一日, 不写当天未收盘的 bar。
"""
import os, sys, json, time, datetime as dt, urllib.request
import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import ifind_data_layer as I

DB = os.path.join(ROOT, "data", "cn_hk_price_db", "a_daily.parquet")
DRY = os.environ.get("DRY_RUN") == "1"
COMPLETE_RATIO = 0.97
EXRIGHT_TOL = 0.001
BATCH = 60


def fs_alert(msg):
    """⛔2026-09-29: 09-24 起 iFinD 令牌过期, 本脚本每天 15:40 崩在 URLError, 只在 /tmp 日志留了回溯,
    价格库停在 09-23 四天没人知道(main 数据资产盘点才发现)。失败与降级都必须发到飞书, 首行带 ⛔ 才过白名单。"""
    if DRY:
        print(f"   [DRY_RUN 不发飞书] {msg}", flush=True); return
    try:
        import subprocess
        subprocess.run(["bash", os.path.expanduser("~/.claude/session-remote/fs-reply.sh"), msg],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, timeout=30)
    except Exception as e:
        print(f"   飞书发送异常 {e}", flush=True)


def die(msg, code=1):
    print(f"⛔ {msg}", flush=True)
    fs_alert(f"⛔[A股价格库] cn_price_db_update 失败, 未写库: {msg}")
    sys.exit(code)


def target_end():
    if os.environ.get("END"):
        return os.environ["END"]
    now = dt.datetime.now()
    d = now.date()
    if now.hour * 100 + now.minute < 1530:
        d = d - dt.timedelta(days=1)
    return d.isoformat()


def fetch_ifind(tickers, start, end):
    rows, failed = [], []
    for i in range(0, len(tickers), BATCH):
        batch = tickers[i:i + BATCH]
        for attempt in range(3):
            r = I.history(",".join(batch), start, end,
                          "open,high,low,close,volume,amount,turnoverRatio,preClose")
            if r.get("errorcode") in (0, "0"):
                break
            time.sleep(2 + attempt * 3)
        else:
            print(f"   批次 {i//BATCH} 三次失败 errorcode={r.get('errorcode')} {r.get('errmsg','')[:60]}", flush=True)
            failed += batch
            continue
        got = set()
        for t in r.get("tables") or []:
            code = t.get("thscode"); tm = t.get("time") or []; tb = t.get("table") or {}
            got.add(code)
            for j, d in enumerate(tm):
                g = lambda k: (tb.get(k) or [None] * len(tm))[j]
                if g("close") is None:
                    continue  # 停牌
                rows.append({"date": d, "ticker": code, "open": g("open"), "high": g("high"),
                             "low": g("low"), "close": g("close"), "volume": g("volume"),
                             "amount": g("amount"), "turn_pct": g("turnoverRatio"), "preclose": g("preClose")})
        failed += [c for c in batch if c not in got]
        if (i // BATCH) % 10 == 0:
            print(f"   已拉 {min(i+BATCH, len(tickers))}/{len(tickers)}", flush=True)
    return pd.DataFrame(rows), failed


def fetch_baostock(tickers, start, end):
    """iFinD 不可用时的备用源(2026-09-29 加)。baostock 单进程(并行 login 会被拉黑), 约 0.3 秒一只。
    字段与 iFinD 同单位: volume=股, amount=元, turn=百分数, preclose=交易所前收盘(除权后), 除权识别照常。
    ⛔免费源收盘后结算慢, 当天的 bar 可能还没有, 由 main() 的末尾裁剪处理, 不在这里补猜。"""
    import baostock as bs, signal
    class _TO(Exception): pass
    def _alarm(sig, frm): raise _TO()
    signal.signal(signal.SIGALRM, _alarm)
    lg = bs.login()
    if lg.error_code != "0":
        die(f"baostock 登录失败 {lg.error_code} {lg.error_msg}")
    rows, failed = [], []
    for i, tk in enumerate(tickers):
        code, ex = tk.split(".")
        got = False
        for attempt in range(2):
            try:
                signal.alarm(15)
                rs = bs.query_history_k_data_plus(f"{ex.lower()}.{code}",
                        "date,open,high,low,close,preclose,volume,amount,turn,tradestatus",
                        start_date=start, end_date=end, frequency="d", adjustflag="3")
                if rs.error_code != "0":
                    signal.alarm(0); time.sleep(1); continue
                while rs.next():
                    d = rs.get_row_data()
                    if d[9] != "1" or not d[4]:
                        continue  # 停牌
                    f = lambda x: float(x) if x not in ("", None) else None
                    rows.append({"date": d[0], "ticker": tk, "open": f(d[1]), "high": f(d[2]), "low": f(d[3]),
                                 "close": f(d[4]), "preclose": f(d[5]), "volume": f(d[6]), "amount": f(d[7]),
                                 "turn_pct": f(d[8])})
                signal.alarm(0); got = True; break
            except _TO:
                signal.alarm(0)
                try: bs.logout(); bs.login()
                except Exception: pass
        if not got:
            failed.append(tk)
        if (i + 1) % 500 == 0:
            print(f"   baostock 已拉 {i+1}/{len(tickers)} 失败 {len(failed)}", flush=True)
    bs.logout()
    return pd.DataFrame(rows), failed


def trade_days(start, end):
    """区间内的 A 股交易日(baostock 交易日历)。用来区分"真的没有交易日"与"有交易日但源还没结算"。
    ⛔取不到日历时返回 None, 调用方按"不确定"处理, 不许当成没有交易日。"""
    try:
        import baostock as bs
        bs.login()
        rs = bs.query_trade_dates(start_date=start, end_date=end)
        out = []
        while rs.next():
            d, flag = rs.get_row_data()[:2]
            if flag == "1":
                out.append(d)
        bs.logout()
        return out if rs.error_code == "0" else None
    except Exception:
        return None


def sina_close(ticker, d):
    """腾讯日K被限流时(2026-09-29 实测 HTTP 501)的第二锚点。"""
    code, ex = ticker.split(".")
    try:
        import requests
        s = requests.Session(); s.trust_env = False
        r = s.get("https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData",
                  params=dict(symbol=f"{ex.lower()}{code}", scale=240, ma="no", datalen=10), timeout=10)
        for x in r.json() or []:
            if x.get("day") == d:
                return float(x["close"])
    except Exception:
        pass
    return None


def tencent_close(ticker, d):
    code, ex = ticker.split(".")
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={ex.lower()}{code},day,{d},{d},1,"
    try:
        j = json.loads(urllib.request.urlopen(url, timeout=10).read())
        k = j["data"][f"{ex.lower()}{code}"].get("day") or []
        return float(k[0][2]) if k else None
    except Exception:
        return None



def backfill_stale(df, last_ok, end):
    """2026-10-12: 股票池原取"最后完整日在库者", 某只股票恰在那天停牌就永久掉出池子(实证: 新华传媒 09-04 停牌,
    09-21 复牌连拉 10 板, 库里一直停在 09-04; 园林股份等共 28 只)。近 120 天出现过、最后日期早于 last_ok 的股票,
    按各自缺口补拉到 min(end, last_ok), 逐只做除权识别后并回。返回 (新df, 补回行数)。"""
    recent = df[df["date"] >= last_ok - pd.Timedelta(days=120)]
    lastd = recent.groupby("ticker")["date"].max()
    stale = lastd[lastd < last_ok]
    if not len(stale) or os.environ.get("UNIVERSE_LIMIT"):
        return df, 0
    cap = min(pd.Timestamp(end), last_ok).date().isoformat()
    add = []
    for tk, d0 in stale.items():
        got, _ = fetch_baostock([tk], (d0 + pd.Timedelta(days=1)).date().isoformat(), cap)
        if len(got): add.append(got)
    if not add:
        print(f"   停牌后复牌补拉: {len(stale)} 只候选, 均无新行(仍停牌或已退市)", flush=True)
        return df, 0
    sa = pd.concat(add, ignore_index=True); sa["date"] = pd.to_datetime(sa["date"])
    for c in ["open", "high", "low", "close", "volume", "amount", "turn_pct", "preclose"]:
        sa[c] = pd.to_numeric(sa[c], errors="coerce")
    sa = sa.drop_duplicates(["ticker", "date"]).sort_values(["ticker", "date"])
    last_close = df.sort_values("date").groupby("ticker")["close"].last()
    last_oshare = df.sort_values("date").groupby("ticker")["oshare"].last()
    sa["prev_close"] = sa.groupby("ticker")["close"].shift(1).fillna(sa["ticker"].map(last_close))
    sa["r"] = sa["preclose"] / sa["prev_close"]
    ev = sa[(sa["r"] - 1).abs() > EXRIGHT_TOL][["ticker", "date", "r"]]
    sa["qfq_factor"] = 1.0; sa["oshare"] = sa["ticker"].map(last_oshare); sa["turn"] = sa["turn_pct"] / 100.0
    cols = ["date", "ticker", "open", "high", "low", "close", "volume", "amount", "oshare", "turn", "qfq_factor"]
    full = pd.concat([df.drop(columns=["adj_close"]), sa[cols]], ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)
    for tk, g in ev.groupby("ticker"):
        idx = full.index[full["ticker"] == tk]
        for _, e in g.sort_values("date").iterrows():
            m = idx[full.loc[idx, "date"] < e["date"]]
            full.loc[m, "qfq_factor"] = full.loc[m, "qfq_factor"] / e["r"]
    full["adj_close"] = full["close"] / full["qfq_factor"]
    full = full[["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn", "qfq_factor"]]
    print(f"   停牌后复牌补拉: {len(stale)} 只候选, 补回 {sa['ticker'].nunique()} 只 {len(sa)} 行, 除权 {len(ev)} 起", flush=True)
    return full, len(sa)


def write_db(full, t0, note):
    tmp = DB + ".tmp"
    full.to_parquet(tmp, index=False)
    chk = pd.read_parquet(tmp, columns=["date"])
    if len(chk) != len(full):
        die("临时文件读回行数不符, 不替换")
    os.replace(DB, DB + ".bak")
    os.replace(tmp, DB)
    print(f"[OK] {note}, 原文件备份为 a_daily.parquet.bak。耗时 {time.time()-t0:.0f}s", flush=True)

def main():
    t0 = time.time()
    # 2026-09-29: 备用源 baostock 全市场约 26 分钟, 手动补跑与 15:40 定时任务可能重叠, 两个写者会互相覆盖
    import fcntl
    global _LOCK
    _LOCK = open(DB + ".lock", "w")
    try:
        fcntl.flock(_LOCK, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("⛔ 另一个 cn_price_db_update 正在运行, 本次退出", flush=True)
        return
    end = target_end()
    print(f"[cn_price_db_update] DRY_RUN={DRY} 截止日={end}", flush=True)
    df = pd.read_parquet(DB)
    print(f"   读入 {len(df):,} 行 {df['ticker'].nunique()} 只", flush=True)

    cnt = df.groupby("date").size().sort_index()
    tail = cnt.tail(40)
    base = tail.max()
    complete = tail[tail >= base * COMPLETE_RATIO]
    last_ok = complete.index.max()
    drop = df["date"] > last_ok
    print(f"   最后完整交易日 {last_ok.date()} ({cnt[last_ok]} 只, 基准 {base}); 丢弃其后残行 {int(drop.sum()):,} 行", flush=True)
    df = df[~drop].copy()

    df, n_back = backfill_stale(df, last_ok, end)
    start = (last_ok + pd.Timedelta(days=1)).date().isoformat()
    if start > end:
        if n_back and not DRY:
            write_db(df, t0, f"无新交易日, 仅写入停牌复牌补拉 {n_back} 行")
        else:
            print("   无需追加, 退出", flush=True)
        return
    universe = sorted(df.loc[df["date"] == last_ok, "ticker"].unique())
    if os.environ.get("UNIVERSE_LIMIT"):   # 仅测试用(须配合 DRY_RUN): 抽样核对的 5 只 + 前 N 只, 覆盖基准改按池子大小
        if not DRY:
            die("UNIVERSE_LIMIT 只能与 DRY_RUN=1 同用")
        keep = ["600519.SH", "000001.SZ", "688758.SH", "300750.SZ", "601318.SH"]
        universe = sorted(set(keep) | set(universe[:int(os.environ["UNIVERSE_LIMIT"])]))
        base = len(universe)
    print(f"   追加区间 {start} 到 {end}, 股票池 {len(universe)} 只(取最后完整日在库者)", flush=True)

    src = "iFinD"
    if os.environ.get("IFIND_ENABLED") != "1":
        # 2026-10-12: iFinD 09-29 起停用, 每次先试它要白耗 86 批×3 次重试; 未显式启用就直接走备用源
        new, failed, ifind_err = pd.DataFrame(), list(universe), "iFinD 已停用(未设 IFIND_ENABLED=1)"
    else:
      try:
        new, failed = fetch_ifind(universe, start, end)
        ifind_err = None if (len(new) or not failed) else f"整批失败 {len(failed)} 只"
      except Exception as e:
        new, failed, ifind_err = pd.DataFrame(), list(universe), f"{type(e).__name__}: {str(e)[:120]}"
    if ifind_err:
        print(f"   ⛔ iFinD 不可用({ifind_err}), 切 baostock 备用源", flush=True)
        src = "baostock"
        new, failed = fetch_baostock(universe, start, end)
    if new.empty and not failed:
        # ⛔2026-09-29: 原来这里直接当"节假日"退出。免费源收盘后未结算时也是全部返回空, 会被误判成节假日静默跳过。
        td = trade_days(start, end)
        if td:
            fs_alert(f"⛔[A股价格库] {src} 对交易日 {td} 还没有数据(未结算), 本次未写库, 库仍停在 {last_ok.date()}, 下次运行再补")
            print(f"   ⛔ 区间内有交易日 {td} 但 {src} 尚无数据(未结算), 未写库", flush=True)
            return
        if td is None:
            die(f"{src} 未返回数据且交易日历取不到, 无法判断是节假日还是未结算")
        print(f"   {start} 到 {end} 无新交易日(周末或节假日), 正常退出", flush=True)
        return
    if new.empty:
        die(f"{src} 未返回任何行且有 {len(failed)} 只失败, 疑似接口或网络故障")
    new["date"] = pd.to_datetime(new["date"])
    for c in ["open", "high", "low", "close", "volume", "amount", "turn_pct", "preclose"]:
        new[c] = pd.to_numeric(new[c], errors="coerce")
    new = new.drop_duplicates(["ticker", "date"]).sort_values(["ticker", "date"])
    print(f"   {src} 返回 {len(new):,} 行; 整只未返回 {len(failed)} 只", flush=True)
    if failed:
        print(f"   未返回样例 {failed[:10]}", flush=True)

    # 逐日覆盖校验
    per = new.groupby("date").size()
    print("   新日期行数:", {d.date().isoformat(): int(n) for d, n in per.items()}, flush=True)
    bad = per[per < base * COMPLETE_RATIO]
    trimmed = []
    # ⛔2026-09-29: 免费源收盘后结算慢, 末尾一两天覆盖不足是常态。只裁掉"末尾连续"的不足日, 前面完整的照写;
    #   不足日若夹在完整日之间(中间缺口), 说明拉数本身有问题, 仍整批不写。
    while len(bad) and bad.index.max() == per.index.max():
        dmax = per.index.max(); trimmed.append(dmax.date().isoformat())
        new = new[new["date"] != dmax]; per = per.drop(dmax); bad = bad.drop(dmax)
    if len(bad):
        die(f"覆盖不足(中间缺口), 不写库: {({d.date().isoformat(): int(n) for d, n in bad.items()})}", 3)
    if trimmed:
        print(f"   末尾未结算日已裁掉, 下次运行再补: {trimmed}", flush=True)
    if new.empty:
        fs_alert(f"⛔[A股价格库] {src} 尚无完整的新交易日(未结算: {trimmed}), 本次未写库, 库仍停在 {last_ok.date()}")
        print("   无完整新交易日可写, 退出", flush=True)
        return

    # 除权识别与因子回溯
    last_close = df.sort_values("date").groupby("ticker")["close"].last()
    last_oshare = df.sort_values("date").groupby("ticker")["oshare"].last()
    new["prev_close"] = new.groupby("ticker")["close"].shift(1)
    new["prev_close"] = new["prev_close"].fillna(new["ticker"].map(last_close))
    new["r"] = new["preclose"] / new["prev_close"]
    ev = new[(new["r"] - 1).abs() > EXRIGHT_TOL][["ticker", "date", "r"]]
    print(f"   识别除权除息事件 {len(ev)} 起" + (f": {ev.head(12).to_dict('records')}" if len(ev) else ""), flush=True)

    new["qfq_factor"] = 1.0
    new["oshare"] = new["ticker"].map(last_oshare)
    new["turn"] = new["turn_pct"] / 100.0
    out_new = new[["date", "ticker", "open", "high", "low", "close", "volume", "amount", "oshare", "turn", "qfq_factor"]].copy()

    full = pd.concat([df.drop(columns=["adj_close"]), out_new], ignore_index=True)
    if len(ev):
        full = full.sort_values(["ticker", "date"]).reset_index(drop=True)
        for tk, g in ev.groupby("ticker"):
            idx = full.index[full["ticker"] == tk]
            for _, e in g.sort_values("date").iterrows():
                m = idx[full.loc[idx, "date"] < e["date"]]
                full.loc[m, "qfq_factor"] = full.loc[m, "qfq_factor"] / e["r"]
    full["adj_close"] = full["close"] / full["qfq_factor"]
    full = full[["date", "ticker", "open", "high", "low", "close", "adj_close", "volume", "amount", "oshare", "turn", "qfq_factor"]]
    full = full.sort_values(["ticker", "date"]).reset_index(drop=True)

    # 校验
    newpart = full[full["date"] > last_ok]
    if newpart["close"].isna().any():
        die("新数据 close 有空值")
    lastd = newpart["date"].max().date().isoformat()
    samp = ["600519.SH", "000001.SZ", "688758.SH", "300750.SZ", "601318.SH"]
    mism = []; checked = 0
    for tk in samp:
        row = newpart[(newpart["ticker"] == tk) & (newpart["date"] == newpart["date"].max())]
        if row.empty:
            continue
        tc = tencent_close(tk, lastd); anchor = "腾讯"
        if tc is None:
            tc = sina_close(tk, lastd); anchor = "新浪"
        v = float(row["close"].iloc[0])
        ok = tc is not None and abs(tc - v) < 0.011
        print(f"   抽样 {tk} {lastd} {src}={v} {anchor}={tc} {'✓' if ok else '⛔'}", flush=True)
        if tc is not None and not ok:
            mism.append(tk)
        if ok:
            checked += 1
    if mism:
        die(f"抽样收盘价与锚点不一致: {mism}")
    if checked < 3:
        die(f"抽样只核对上 {checked} 只(腾讯与新浪锚点都取不到), 不能确认新数据正确")
    print(f"   合并后 {len(full):,} 行, 新增 {len(newpart):,} 行, 覆盖到 {lastd}", flush=True)

    if DRY:
        print(f"[DRY_RUN] 校验全部通过, 未写库。耗时 {time.time()-t0:.0f}s", flush=True)
        return
    tmp = DB + ".tmp"
    full.to_parquet(tmp, index=False)
    chk = pd.read_parquet(tmp, columns=["date"])
    if len(chk) != len(full):
        die("临时文件读回行数不符, 不替换")
    os.replace(DB, DB + ".bak")
    os.replace(tmp, DB)
    print(f"[OK] 已写库, 原文件备份为 a_daily.parquet.bak。耗时 {time.time()-t0:.0f}s", flush=True)
    if src != "iFinD" or trimmed:
        fs_alert(f"⛔[A股价格库] 已用 {src} 补到 {lastd}" + (f", 未结算待补: {trimmed}" if trimmed else "")
                 + ("。iFinD 不可用(令牌可能过期, 需去 quantapi.10jqka.com.cn 重新生成)" if src != "iFinD" else ""))


if __name__ == "__main__":
    main()
