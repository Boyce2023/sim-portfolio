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


def die(msg, code=1):
    print(f"⛔ {msg}", flush=True)
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


def tencent_close(ticker, d):
    code, ex = ticker.split(".")
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={ex.lower()}{code},day,{d},{d},1,"
    try:
        j = json.loads(urllib.request.urlopen(url, timeout=10).read())
        k = j["data"][f"{ex.lower()}{code}"].get("day") or []
        return float(k[0][2]) if k else None
    except Exception:
        return None


def main():
    t0 = time.time()
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

    start = (last_ok + pd.Timedelta(days=1)).date().isoformat()
    if start > end:
        print("   无需追加, 退出", flush=True)
        return
    universe = sorted(df.loc[df["date"] == last_ok, "ticker"].unique())
    print(f"   追加区间 {start} 到 {end}, 股票池 {len(universe)} 只(取最后完整日在库者)", flush=True)

    new, failed = fetch_ifind(universe, start, end)
    if new.empty and not failed:
        print(f"   {start} 到 {end} 无新交易日(周末或节假日), 正常退出", flush=True)
        return
    if new.empty:
        die(f"iFinD 未返回任何行且有 {len(failed)} 只失败, 疑似接口或网络故障")
    new["date"] = pd.to_datetime(new["date"])
    for c in ["open", "high", "low", "close", "volume", "amount", "turn_pct", "preclose"]:
        new[c] = pd.to_numeric(new[c], errors="coerce")
    new = new.drop_duplicates(["ticker", "date"]).sort_values(["ticker", "date"])
    print(f"   iFinD 返回 {len(new):,} 行; 整只未返回 {len(failed)} 只", flush=True)
    if failed:
        print(f"   未返回样例 {failed[:10]}", flush=True)

    # 逐日覆盖校验
    per = new.groupby("date").size()
    print("   新日期行数:", {d.date().isoformat(): int(n) for d, n in per.items()}, flush=True)
    bad = per[per < base * COMPLETE_RATIO]
    if len(bad):
        die(f"覆盖不足, 不写库: {({d.date().isoformat(): int(n) for d, n in bad.items()})}", 3)

    # 除权识别与因子回溯
    last_close = df[df["date"] == last_ok].set_index("ticker")["close"]
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
    mism = []
    for tk in samp:
        row = newpart[(newpart["ticker"] == tk) & (newpart["date"] == newpart["date"].max())]
        if row.empty:
            continue
        tc = tencent_close(tk, lastd)
        v = float(row["close"].iloc[0])
        ok = tc is not None and abs(tc - v) < 0.011
        print(f"   抽样 {tk} {lastd} iFinD={v} 腾讯={tc} {'✓' if ok else '⛔'}", flush=True)
        if tc is not None and not ok:
            mism.append(tk)
    if mism:
        die(f"抽样收盘价与腾讯不一致: {mism}")
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


if __name__ == "__main__":
    main()
