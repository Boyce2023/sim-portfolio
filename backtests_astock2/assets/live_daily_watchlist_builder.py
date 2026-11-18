# -*- coding: utf-8 -*-
"""
live_daily_watchlist_builder.py
当日题目专属：关注名单（同花顺置顶自动同步）全维基本面与盘口特征构建器
输出字段：市值（总/流/真实自由流通）、题材、连板与多日多板、真实换手率上限、过去20日走势K线、竞价价格、过去20日回撤。
"""
import os
import json
import urllib.request
import numpy as np
import pandas as pd
import pyarrow.dataset as ds

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
A_DAILY = f"{SIM_DIR}/data/cn_hk_price_db/a_daily.parquet"
HOLDERS_PATH = f"{SIM_DIR}/backtests_astock/sandbox_lab/grand_factor_matrix_20261112/pit_top10_all_codes.json"
KPL_MERGED = f"{SIM_DIR}/data/kpl_plates_2018_2026_merged.jsonl"

_DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))

FALLBACK_THEMES = {
    "001201": "猪肉养殖 · 供港生猪主业",
    "601595": "文化传媒 · AI视频与院线IP",
    "002242": "智能小家电 · 消费龙头",
}


def _fetch_tc_klines(c6: str, count: int = 35) -> list[tuple]:
    q_sym = ("sh" if c6.startswith("6") else "sz") + c6
    for proto in ("https", "http"):
        url = f"{proto}://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={q_sym},day,,,{count},qfq"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            dat = json.loads(_DIRECT.open(req, timeout=4).read().decode("utf-8", "ignore")).get("data", {}).get(q_sym, {})
            rows = dat.get("qfqday") or dat.get("day") or []
            if rows:
                return [(str(r[0])[:10], float(r[1]), float(r[3]), float(r[4]), float(r[2]), float(r[5])) for r in rows if len(r) >= 6]
        except Exception:
            pass
    # 新浪日线兜底（防腾讯 fqKline 偶发 501）
    try:
        s_url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var/CN_MarketDataService.getKLineData?symbol={q_sym}&scale=240&ma=no&datalen={count}"
        txt = _DIRECT.open(urllib.request.Request(s_url, headers={"User-Agent": "Mozilla/5.0"}), timeout=4).read().decode("utf-8", "ignore")
        i, j = txt.find("["), txt.rfind("]")
        if i >= 0 and j > i:
            return [(str(r["day"])[:10], float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), float(r.get("volume", 0.0)) / 100.0) for r in json.loads(txt[i:j + 1])]
    except Exception:
        pass
    return []


def compute_streak_and_ndmb(bars_df: pd.DataFrame) -> tuple[int, int, str]:
    """根据截至D1的日线序列计算：当前连板数、前一日连板数、以及含多日多板的通俗描述"""
    if bars_df.empty:
        return 0, 0, "暂无连板"
    c = bars_df["close"].to_numpy(dtype=float)
    pre = np.roll(c, 1)
    pre[0] = float(bars_df["open"].iloc[0])
    zt_px = np.floor(pre * 1.10 * 100.0 + 0.5) / 100.0
    pct = c / np.maximum(pre, 0.01) - 1.0
    is_zt = (c >= zt_px - 0.011) & (pct >= 0.094)
    is_zt[0] = False

    streak = 0
    for v in is_zt[::-1]:
        if v:
            streak += 1
        else:
            break
    prev_streak = 0
    for v in is_zt[:-1][::-1]:
        if v:
            prev_streak += 1
        else:
            break

    w20 = is_zt[-20:]
    m20 = int(w20.sum())
    ndmb_tag = ""
    if m20 >= 2:
        first_idx = int(np.argmax(w20))
        n_days = len(w20) - first_idx
        if m20 > streak:
            ndmb_tag = f"{n_days}天{m20}板"

    if streak >= 2:
        base = f"{streak}连板"
    elif streak == 1:
        base = "昨日首板"
    elif prev_streak >= 2:
        base = f"昨断板(前{prev_streak}板)"
    elif prev_streak == 1:
        base = "昨首板断板"
    else:
        base = "趋势震荡"

    full_str = f"{base} · {ndmb_tag}" if ndmb_tag else (f"{base}(20日{m20}板)" if m20 >= 1 else f"{base}(20日0板)")
    return streak, prev_streak, full_str


def load_stock_static_profiles(codes: list[str], d1_date: str) -> dict[str, dict]:
    """一次性从本地 Parquet + 股东库 + KPL库 提取任意股票池的静态底数（供盘前打包与盘中复用）"""
    uniq_codes = sorted({str(c)[:6].zfill(6) for c in codes if str(c).strip()})
    if not uniq_codes:
        return {}

    holders = json.load(open(HOLDERS_PATH, "r", encoding="utf-8")) if os.path.exists(HOLDERS_PATH) else {}
    kpl_map = {}
    if os.path.exists(KPL_MERGED):
        target_set = set(uniq_codes)
        with open(KPL_MERGED, "r", encoding="utf-8") as f:
            for ln in f:
                it = json.loads(ln)
                if it.get("date", "") > d1_date:
                    continue
                for pl in it.get("plates", it.get("themes", [])):
                    pn = str(pl.get("plate") or pl.get("plate_name") or "").strip()
                    if not pn or pn in ("其他", "公告", "ST板块", "次新股"):
                        continue
                    for st in pl.get("stocks", []):
                        c6 = str(st[0]).zfill(6)
                        if c6 in target_set:
                            rsn = str(st[2] if len(st) > 2 else "").strip().split("\n")[0][:18]
                            kpl_map[c6] = f"{pn} · {rsn}" if (rsn and rsn != pn) else pn

    tickers = [f"{c}.SH" if c.startswith("6") else f"{c}.SZ" for c in uniq_codes]
    cols = ["date", "ticker", "open", "high", "low", "close", "turn", "oshare", "amount"]
    df = ds.dataset(A_DAILY, format="parquet").scanner(
        columns=cols,
        filter=(ds.field("ticker").isin(tickers)) & (ds.field("date") >= pd.Timestamp("2021-06-01")),
    ).to_table().to_pandas()
    df["c6"] = df["ticker"].astype(str).str[:6]
    df["dt_str"] = df["date"].dt.strftime("%Y-%m-%d")
    df = df[df["dt_str"] <= d1_date].sort_values(["c6", "dt_str"])

    rt_d1_map = {}
    rt_meta_map = {}
    q_all = [("sh" if c.startswith("6") else "sz") + c for c in uniq_codes]
    for idx in range(0, len(q_all), 60):
        try:
            u_rt = "http://qt.gtimg.cn/q=" + ",".join(q_all[idx: idx + 60])
            txt_rt = _DIRECT.open(urllib.request.Request(u_rt, headers={"User-Agent": "Mozilla/5.0"}), timeout=3).read().decode("gbk", "ignore")
            for ln in txt_rt.strip().splitlines():
                if '="' not in ln:
                    continue
                k_q, v_q = ln.split('="', 1)
                p = v_q.strip('";').split("~")
                if len(p) > 45:
                    c6_q = k_q[-6:]
                    rt_meta_map[c6_q] = (str(p[1]).strip(), float(p[44] or 0), float(p[45] or 0))
                    ts = str(p[30])[:8]
                    dt_rt = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}" if len(ts) == 8 else ""
                    c_rt, o_rt, h_rt, l_rt = float(p[3] or 0), float(p[5] or 0), float(p[33] or 0), float(p[34] or 0)
                    v_shou_rt = float(p[36] or 0)
                    to_pct_rt = float(p[38] or 0)
                    amt_yi_rt = float(p[37] or 0) / 10000.0
                    if dt_rt == d1_date and c_rt > 0 and o_rt > 0:
                        rt_d1_map[c6_q] = (dt_rt, o_rt, h_rt or max(o_rt, c_rt), l_rt or min(o_rt, c_rt), c_rt, v_shou_rt, to_pct_rt, amt_yi_rt)
        except Exception:
            pass

    profiles = {}
    for c6 in uniq_codes:
        sub = df[df["c6"] == c6].copy().reset_index(drop=True)
        tc_kl = _fetch_tc_klines(c6, count=35)
        rt_b = rt_d1_map.get(c6)
        if rt_b and (not tc_kl or tc_kl[-1][0] < d1_date):
            tc_kl = [x for x in tc_kl if x[0] < d1_date] + [(rt_b[0], rt_b[1], rt_b[2], rt_b[3], rt_b[4], rt_b[5])]
        if sub.empty and tc_kl:
            sub = pd.DataFrame([(x[0], x[1], x[2], x[3], x[4], x[5] * 100.0 * x[4]) for x in tc_kl], columns=["dt_str", "open", "high", "low", "close", "amount"])
            sub["turn"] = (rt_b[6] / 100.0) if (rt_b and rt_b[6] > 0) else 0.08
            sub["oshare"] = 0.0
        elif tc_kl and (sub.empty or sub["dt_str"].iloc[-1] < d1_date):
            last_dt = sub["dt_str"].iloc[-1]
            osh_last = float(sub["oshare"].iloc[-1]) if len(sub) else 0.0
            add_rows = []
            for dt_s, o, h, l, c, v_shou in tc_kl:
                if last_dt < dt_s <= d1_date:
                    if rt_b and dt_s == d1_date and rt_b[6] > 0:
                        to_est = rt_b[6] / 100.0
                        amt_est = rt_b[7] * 1e8 if rt_b[7] > 0 else v_shou * 100.0 * c
                    else:
                        to_est = (v_shou * 100.0 / osh_last) if osh_last > 1000 else 0.08
                        amt_est = v_shou * 100.0 * c
                    add_rows.append({"c6": c6, "dt_str": dt_s, "open": o, "high": h, "low": l, "close": c, "turn": to_est, "oshare": osh_last, "amount": amt_est})
            if add_rows:
                sub = pd.concat([sub, pd.DataFrame(add_rows)], ignore_index=True)

        if sub.empty:
            continue

        h_rows = [x for x in holders.get(c6, []) if str(x[0]) <= d1_date] or holders.get(c6, [])
        lock_pct = round(float(max(h_rows, key=lambda x: x[1])[2]), 1) if h_rows else 35.0
        # 真实换手上限：去掉前十大流通锁仓股东后，外面剩余筹码对应的最大名义换手率上限 = 100% - 十大锁仓占比
        to_cap_after_lock = round(max(5.0, 100.0 - lock_pct), 1)

        d1_t_raw = float(sub["turn"].iloc[-1] or 0.0)
        d1_nom_to = round(d1_t_raw * 100.0 if d1_t_raw < 1.5 else d1_t_raw, 1)

        streak, prev_streak, board_str = compute_streak_and_ndmb(sub.tail(35))
        # 用前复权腾讯K线做最近20根走势（含成交额/量列供 renderCompactKLine 绘红绿柱+量柱）
        kl_src = [(o, h, l, c, max(0.05, round(v_shou * 100.0 * c / 1e8, 2))) for (dt_s, o, h, l, c, v_shou) in tc_kl if dt_s <= d1_date][-20:]
        if len(kl_src) < 10:
            kl_src = [
                (float(r.open), float(r.high), float(r.low), float(r.close), max(0.05, round(float(getattr(r, "amount", 0.0) or 1e7) / 1e8, 2)))
                for r in sub.tail(20).itertuples()
            ]

        c_arr = np.array([x[3] for x in kl_src], dtype=float)
        h_arr = np.array([x[1] for x in kl_src], dtype=float)
        l_arr = np.array([x[2] for x in kl_src], dtype=float)
        pre20_base = float(kl_src[0][0]) if kl_src else float(c_arr[0])
        ret_20d = round((c_arr[-1] / max(pre20_base, 0.01) - 1.0) * 100.0, 1)
        ma5_d1 = float(np.mean(c_arr[-5:])) if len(c_arr) >= 5 else float(c_arr[-1])
        trend_tag = "站5日线" if c_arr[-1] >= ma5_d1 * 0.998 else "破5日线"

        h20 = float(np.max(h_arr))
        dd_d1 = round(max(0.0, (1.0 - c_arr[-1] / max(h20, 0.01)) * 100.0), 1)
        run_max = np.maximum.accumulate(h_arr)
        max_dd_20d = round(float(np.max((run_max - l_arr) / np.maximum(run_max, 0.01)) * 100.0), 1)

        d1_c = round(float(sub["close"].iloc[-1]), 2)
        osh = float(sub["oshare"].iloc[-1] or 0.0)
        fmcap_est = round(d1_c * osh / 1e8, 1) if osh > 1e5 else 0.0
        nm_rt, fm_rt, tm_rt = rt_meta_map.get(c6, ("", 0.0, 0.0))

        profiles[c6] = {
            "code": c6,
            "name": nm_rt or c6,
            "d1_close": d1_c,
            "fmcap_d1": round(fm_rt, 1) if fm_rt > 0 else fmcap_est,
            "tmcap_d1": round(tm_rt, 1) if tm_rt > 0 else fmcap_est,
            "lock_pct": lock_pct,
            "to_cap": to_cap_after_lock,
            "d1_nom_to": d1_nom_to,
            "streak": streak,
            "prev_streak": prev_streak,
            "board_str": board_str,
            "theme": kpl_map.get(c6) or FALLBACK_THEMES.get(c6, "主线轮动"),
            "klines_20d": [[round(o, 2), round(h, 2), round(l, 2), round(c, 2), round(v, 2)] for (o, h, l, c, v) in kl_src],
            "h20": round(h20, 2),
            "ret_20d": ret_20d,
            "trend_tag": trend_tag,
            "dd_d1": dd_d1,
            "max_dd_20d": max_dd_20d,
        }
    return profiles
