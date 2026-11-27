#!/opt/homebrew/bin/python3.13
# -*- coding: utf-8 -*-
"""rd_master_trading_data_sync.py — 六大主战策略 V20.0 全链路零延迟数据同步、缓存重算与 SLA 硬门禁总控"""
import os, sys, json, time, sqlite3, datetime, subprocess, urllib.request
from concurrent.futures import ThreadPoolExecutor
import pyarrow.dataset as ds

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

ROOT = "/Users/huaichuaibeimeng/claude-projects"
SIM_DIR = f"{ROOT}/sim-portfolio"
DATA_DIR = f"{SIM_DIR}/data"
SCRIPTS_DIR = f"{SIM_DIR}/scripts"
ND_DIR = f"{ROOT}/news-dashboard"
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from rd_incremental_sources import sync_index_klines_cache, sync_lhb_parquets, sync_ths_kpl_and_micro_tape

def _probe_tencent_sh_date() -> str:
    try:
        import urllib.request
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        raw = op.open(urllib.request.Request("http://qt.gtimg.cn/q=sh000001", headers={"User-Agent": "Mozilla/5.0"}), timeout=3).read().decode("gbk", "ignore")
        p = raw.split('="', 1)[1].split("~")
        ts = str(p[30])[:8]
        return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}" if len(ts) == 8 and ts.isdigit() else ""
    except Exception:
        return ""

def _verify_cross_script_zero_drift() -> list[str]:
    errs = []
    try:
        bt2 = f"{SIM_DIR}/backtests_astock2"
        for p in (SCRIPTS_DIR, bt2, f"{bt2}/assets"):
            if p not in sys.path:
                sys.path.insert(0, p)
        from fast_1to2_today import evaluate_1to2_v19_df
        from live_daily_question_builder import score_auction_candidates
        from live_3to4_v40_engine import score_single_3to4_v40_row
        from score_3to4_v31_card import score_single_3to4_row

        c1 = json.load(open(f"{DATA_DIR}/1to2_premarket_cache.json", encoding="utf-8"))
        mock_q = {}
        for i, x in enumerate(c1.get("candidates", [])):
            pre = float(x["pre_c"])
            op = round(pre * (1.0 + 0.032 + (i % 5) * 0.008), 2)
            mock_q[x["c6"]] = {"name": x.get("name",""), "pre": pre, "open": op, "low": op, "high": op, "cur": op, "q_dt": c1.get("next_dt", "2099-01-01")}
        df_ssot, _ = evaluate_1to2_v19_df(c1, mock_q)
        sc_quiz, _ = score_auction_candidates(c1, mock_q)
        if not df_ssot.empty:
            m1 = {r["c6"]: (round(float(r["tot"]), 2), bool(r["ok"])) for _, r in df_ssot.iterrows()}
            m2 = {r["c6"]: (round(float(r["tot"]), 2), bool(r["ok"])) for r in sc_quiz}
            if m1 != m2:
                errs.append("drift_1to2_ssot_vs_quiz")

        c3 = json.load(open(f"{DATA_DIR}/3to4_premarket_cache.json", encoding="utf-8"))
        for r in c3.get("candidates", []):
            row = dict(r, **c3.get("env", {}), open_pct=0.055, buyable_open=True, is_top1_3b_open=True, plate_fb_ho_cnt=2, plate_fb_yz_cnt=0, plate_peers_open_avg=0.02)
            r_a = score_single_3to4_v40_row(row)
            r_b = score_single_3to4_row(row)
            if int(r_a["score"]) != int(r_b["score"]) or bool(r_a["passed_skeleton"]) != bool(r_b["passed_skeleton"]):
                errs.append(f"drift_3to4_v40_vs_card({r['code']})")
    except Exception as e:
        errs.append(f"drift_check_exception({e})")
    return errs

def _get_trade_dates() -> list[str]:
    tbl = ds.dataset(f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet", format="parquet").scanner(
        columns=["date"], filter=(ds.field("date") >= ds.scalar(datetime.date(2026, 9, 1))) if hasattr(ds, "scalar") else None
    ).to_table()
    s = sorted(set(d.strftime("%Y-%m-%d") for d in tbl.column("date").to_pylist() if d))
    return s[-40:]

def _sync_ir_qa_recent():
    pit_db = f"{DATA_DIR}/cninfo_notices_5y_pit.db"
    ir_db = f"{SIM_DIR}/backtests_astock2/data_5y/cninfo_ir_qa_5y_pit.db"
    data_ir_db = f"{DATA_DIR}/cninfo_ir_qa_5y_pit.db"
    if not (os.path.exists(pit_db) and os.path.exists(ir_db)): return ""
    cut = (datetime.date.today() - datetime.timedelta(days=15)).isoformat()
    c_src = sqlite3.connect(f"file:{pit_db}?mode=ro", uri=True)
    rows = c_src.execute(
        "SELECT ann_id, sec_code, sec_name, pub_datetime_cst, trade_date_avail, title FROM notices "
        "WHERE pub_datetime_cst >= ? AND (title LIKE '%活动记录%' OR title LIKE '%投资者关系%')", (cut,)
    ).fetchall()
    c_src.close()
    c_dst = sqlite3.connect(ir_db, timeout=30.0)
    if rows:
        now_s = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c_dst.executemany(
            "INSERT OR IGNORE INTO ir_qa (announcement_id, sec_code, sec_name, pub_datetime_cst, trade_date_avail, title, fetched_at, fetch_status) VALUES (?,?,?,?,?,?,?,'META_SYNC')",
            [(r[0], r[1], r[2], r[3], r[4], r[5], now_s) for r in rows]
        )
        c_dst.commit()
    mx = c_dst.execute("SELECT max(pub_datetime_cst) FROM ir_qa").fetchone()[0] or ""
    c_dst.close()
    # 原子热备同步到 data/cninfo_ir_qa_5y_pit.db，消灭双库分叉（WAL安全）
    try:
        tmp_ir = data_ir_db + ".tmp"
        if os.path.exists(tmp_ir):
            os.remove(tmp_ir)
        b_src = sqlite3.connect(f"file:{ir_db}?mode=ro", uri=True)
        b_dst = sqlite3.connect(tmp_ir)
        b_src.backup(b_dst)
        b_dst.close()
        b_src.close()
        os.replace(tmp_ir, data_ir_db)
    except Exception as e:
        print(f"[WARN] atomic copy ir_qa to data/ failed: {e}", file=sys.stderr)
    return mx[:10]

def _sync_st_universe_union(latest_dt: str) -> dict:
    """拉取腾讯实时00/60活跃股票中名称含ST或退的代码，只增不减并集回写 st_universe.json"""
    st_path = f"{DATA_DIR}/st_universe.json"
    old_js = json.load(open(st_path, "r", encoding="utf-8")) if os.path.exists(st_path) else {"_meta": {}, "codes": []}
    old_codes = {str(x)[:6].zfill(6) for x in old_js.get("codes", [])}
    try:
        tbl = ds.dataset(f"{DATA_DIR}/cn_hk_price_db/a_daily.parquet", format="parquet").scanner(
            columns=["date", "ticker"], filter=(ds.field("date") >= ds.scalar(datetime.date.fromisoformat(latest_dt) - datetime.timedelta(days=10))) if hasattr(ds, "scalar") else None
        ).to_table().to_pandas()
        tbl["c6"] = tbl["ticker"].astype(str).str[:6]
        tbl["dt"] = tbl["date"].dt.strftime("%Y-%m-%d")
        use_dt = latest_dt if (tbl["dt"] == latest_dt).any() else tbl["dt"].max()
        active_0060 = sorted(tbl[(tbl["dt"] == use_dt) & (tbl["c6"].str.startswith(("00", "60")))]["c6"].unique().tolist())
        def _fetch_chunk(ch):
            ql = [f"{'sh' if c.startswith('6') else 'sz'}{c}" for c in ch]
            op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            raw = op.open(urllib.request.Request("http://qt.gtimg.cn/q=" + ",".join(ql), headers={"User-Agent": "Mozilla/5.0"}), timeout=4).read().decode("gbk", "ignore")
            out = {}
            for ln in raw.splitlines():
                if "~" not in ln: continue
                p = ln.split("~")
                if len(p) > 4:
                    out[p[2].strip()] = p[1].strip()
            return out
        chunks = [active_0060[i:i+80] for i in range(0, len(active_0060), 80)]
        qmap = {}
        with ThreadPoolExecutor(max_workers=24) as ex:
            for r in ex.map(_fetch_chunk, chunks):
                qmap.update(r)
        if len(qmap) < 2000:
            return {"ok": False, "count": len(old_codes), "added": []}
        live_st = {c for c, nm in qmap.items() if ("ST" in nm.upper() or "退" in nm)}
        added = sorted(live_st - old_codes)
        if added or old_js.get("_meta", {}).get("asof", "") < latest_dt:
            union_codes = sorted(old_codes | live_st)
            new_js = {
                "_meta": {
                    **old_js.get("_meta", {}),
                    "asof": latest_dt,
                    "n": len(union_codes),
                    "source": "只增不减并集: 历史退市/ST底表 ∪ 腾讯实时00/60名称含ST或退",
                    "last_added": [(c, qmap[c]) for c in added] if added else old_js.get("_meta", {}).get("last_added", []),
                },
                "codes": union_codes,
            }
            tmp_st = st_path + ".tmp"
            json.dump(new_js, open(tmp_st, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            os.replace(tmp_st, st_path)
            return {"ok": True, "count": len(union_codes), "added": added}
        return {"ok": True, "count": len(old_codes), "added": []}
    except Exception as e:
        print(f"[WARN] _sync_st_universe_union failed: {e}", file=sys.stderr)
        return {"ok": False, "count": len(old_codes), "added": []}

def _run_cmd_safe(cmd, timeout=120, cwd=None, quiet=False):
    kw = {"check": False, "timeout": timeout}
    if cwd:
        kw["cwd"] = cwd
    if quiet:
        kw["stdout"] = subprocess.DEVNULL
        kw["stderr"] = subprocess.DEVNULL
    try:
        return subprocess.run(cmd, **kw).returncode, None
    except subprocess.TimeoutExpired:
        return -9, "timeout"
    except Exception as e:
        return -1, str(e)


def main():
    t0 = time.time()
    now = datetime.datetime.now()
    today_s = now.strftime("%Y-%m-%d")
    hm = now.hour * 100 + now.minute
    errors = []

    # Stage 0: 若工作日 >=15:15 且日线未到今日，先跑并发日线入库（~15秒）
    t_dates = _get_trade_dates()
    if now.weekday() < 5 and hm >= 1515 and (not t_dates or t_dates[-1] < today_s):
        _run_cmd_safe([sys.executable, f"{SCRIPTS_DIR}/cn_price_db_update.py"], timeout=240)
        t_dates = _get_trade_dates()
    a_daily_max = t_dates[-1] if t_dates else ""
    if now.weekday() < 5 and hm >= 1515:
        sh_dt = _probe_tencent_sh_date()
        if sh_dt and (not t_dates or sh_dt > t_dates[-1]):
            t_dates.append(sh_dt)
    latest_dt = t_dates[-1]
    prev_dt = t_dates[-2] if len(t_dates) >= 2 else latest_dt

    # Wave 1 (DAG 并发数据入库): 所有互不冲突的数据源同时并发拉取
    def _w1_kpl_chain():
        loc_err = []
        if hm >= 1515 and now.weekday() < 5:
            with ThreadPoolExecutor(max_workers=2) as kex:
                f_v = kex.submit(_run_cmd_safe, [sys.executable, f"{ND_DIR}/astock_concept_vocab.py", "--today"], 90)
                f_z = kex.submit(_run_cmd_safe, [sys.executable, f"{SCRIPTS_DIR}/kpl_archive.py", "zdjk"], 45, SIM_DIR)
                if f_v.result()[1] == "timeout":
                    loc_err.append("kpl_vocab_timeout")
                if f_z.result()[1] == "timeout":
                    loc_err.append("kpl_zdjk_timeout")
        kt_max = sync_ths_kpl_and_micro_tape(t_dates)
        return kt_max, loc_err

    def _w1_cninfo_ir_chain():
        rc2, ex2 = _run_cmd_safe([sys.executable, f"{SCRIPTS_DIR}/backfill_cninfo_5y_pit.py", "--recent"], 150)
        loc_err = []
        if rc2 != 0:
            loc_err.append(f"backfill_cninfo_5y_pit rc={rc2}" + (f"({ex2})" if ex2 else ""))
        ir_m = _sync_ir_qa_recent()
        return ir_m, loc_err

    def _w1_notices():
        rc1, ex1 = _run_cmd_safe([sys.executable, f"{SCRIPTS_DIR}/sync_notices_db.py", "--recent"], 120)
        return [] if rc1 == 0 else [f"sync_notices_db rc={rc1}" + (f"({ex1})" if ex1 else "")]

    def _w1_concepts_dry():
        _, ex = _run_cmd_safe([sys.executable, f"{ND_DIR}/astock_concepts.py", "--skip-extract", "--dry"], 35)
        if ex == "timeout":
            print("[WARN] astock_concepts --dry timed out after 35s, continuing core sync", flush=True)

    def _w1_community():
        rc_c, ex_c = _run_cmd_safe([sys.executable, f"{SCRIPTS_DIR}/sync_community_live_to_pit.py"], 45)
        if rc_c != 0:
            print(f"[WARN] sync_community_live_to_pit rc={rc_c} ({ex_c})", file=sys.stderr)

    t_w1 = time.time()
    with ThreadPoolExecutor(max_workers=8) as ex1:
        fut_kpl = ex1.submit(_w1_kpl_chain)
        fut_cninfo = ex1.submit(_w1_cninfo_ir_chain)
        fut_notices = ex1.submit(_w1_notices)
        fut_idx = ex1.submit(sync_index_klines_cache, latest_dt)
        fut_lhb = ex1.submit(sync_lhb_parquets, latest_dt)
        fut_st = ex1.submit(_sync_st_universe_union, latest_dt)
        fut_comm = ex1.submit(_w1_community)
        fut_dry = ex1.submit(_w1_concepts_dry)

        kpl_tape_max, kpl_errs = fut_kpl.result()
        ir_max, cninfo_errs = fut_cninfo.result()
        errors.extend(kpl_errs)
        errors.extend(cninfo_errs)
        errors.extend(fut_notices.result())
        idx_max = fut_idx.result()
        lhb_max = fut_lhb.result()
        st_sync = fut_st.result()
        fut_comm.result()
        fut_dry.result()
    w1_sec = round(time.time() - t_w1, 2)

    # Wave 2 (DAG 并发策略缓存重算 + 独立监控刷新): 6路策略缓存 + 国队监控 + 晨间新闻并行执行
    f_4to5 = f"{SCRIPTS_DIR}/fast_4to5_today.py" if os.path.exists(f"{SCRIPTS_DIR}/fast_4to5_today.py") else f"{SIM_DIR}/backtests_astock2/fast_4to5_today.py"
    cache_builders = [
        ("s5_1to2",        [sys.executable, f"{SCRIPTS_DIR}/fast_1to2_today.py", "--build-cache"],        f"{DATA_DIR}/1to2_premarket_cache.json"),
        ("s1_high_dragon", [sys.executable, f"{SCRIPTS_DIR}/fast_high_dragon_today.py", "--build-cache"], f"{DATA_DIR}/high_dragon_premarket_cache.json"),
        ("s2_3to4",        [sys.executable, f"{SCRIPTS_DIR}/fast_3to4_today.py", "--build-cache"],        f"{DATA_DIR}/3to4_premarket_cache.json"),
        ("s3_4to5",        [sys.executable, f"{f_4to5}", "--build-cache"],                                f"{DATA_DIR}/4to5_premarket_cache.json"),
        ("s4_pry",         [sys.executable, f"{SCRIPTS_DIR}/fast_pry_today.py", "--build-cache"],         f"{DATA_DIR}/pry_premarket_cache.json"),
        ("s6_2to3",        [sys.executable, f"{SCRIPTS_DIR}/fast_2to3_today.py", "--build-cache"],        f"{DATA_DIR}/2to3_premarket_cache.json"),
        ("s7_20cm_deepopen", [sys.executable, f"{SCRIPTS_DIR}/fast_20cm_deepopen_today.py", "--build-cache"], f"{DATA_DIR}/20cm_deepopen_premarket_cache.json"),
    ]

    def _build_one(item):
        key, cmd, cpath = item
        rc, ex = _run_cmd_safe(cmd, timeout=120)
        return key, cpath, rc, ex

    t_w2 = time.time()
    cache_status = {}
    with ThreadPoolExecutor(max_workers=8) as ex2:
        cb_futs = [ex2.submit(_build_one, it) for it in cache_builders]
        fut_nt = ex2.submit(_run_cmd_safe, [sys.executable, f"{SIM_DIR}/backtests_astock2/csrc_policy_model/csrc_national_team_monitor.py", "--today"], 45, None, True)
        fut_news = ex2.submit(_run_cmd_safe, [sys.executable, f"{SCRIPTS_DIR}/news_layer.py"], 45, None, True)

        for f in cb_futs:
            key, cpath, rc, ex = f.result()
            if rc != 0 or not os.path.exists(cpath):
                if key == "s3_4to5":
                    print(f"[WARN] optional R&D {key}_build_failed(rc={rc}), non-blocking", flush=True)
                    cache_status[key] = {"ok": False, "optional_rd": True, "rc": rc}
                else:
                    errors.append(f"{key}_build_failed(rc={rc})")
                    cache_status[key] = {"ok": False}
                continue
            js = json.load(open(cpath, "r", encoding="utf-8"))
            c_dt = js.get("as_of_d1") or js.get("sig_date") or js.get("d3_date") or js.get("d1_date") or ""
            cands_arr = js.get("candidates") or []
            n_cands = len(cands_arr)
            ok = (c_dt >= latest_dt)
            if key == "s5_1to2" and js.get("used_ths_plate_fallback", False):
                ok = False
                errors.append("s5_1to2_used_ths_fallback_not_kpl")
            if key == "s2_3to4" and n_cands > 0:
                if any(("pos20_d0" not in x or "xq_cnt_2d" not in x) for x in cands_arr):
                    ok = False
                    errors.append("s2_3to4_missing_v40_fields")
            if not ok:
                if key == "s3_4to5":
                    print(f"[WARN] optional R&D {key}_stale({c_dt}<{latest_dt}), non-blocking", flush=True)
                else:
                    errors.append(f"{key}_stale({c_dt}<{latest_dt})")
            cache_status[key] = {"ok": ok, "signal_date": c_dt, "candidates": n_cands, "mtime": datetime.datetime.fromtimestamp(os.path.getmtime(cpath)).strftime("%Y-%m-%d %H:%M:%S")}

        # Wave 2b: 每日考题与零漂移校验依赖刚生成的策略缓存，并行执行
        fut_lq = ex2.submit(_run_cmd_safe, [sys.executable, f"{SIM_DIR}/backtests_astock2/live_daily_question_builder.py", "--premarket"], 90)
        fut_drift = ex2.submit(_verify_cross_script_zero_drift)

        rc_lq, ex_lq = fut_lq.result()
        if ex_lq == "timeout":
            errors.append("live_daily_premarket_timeout")
        elif rc_lq != 0:
            errors.append(f"live_daily_premarket_rc({rc_lq})")
        errors.extend(fut_drift.result())
        fut_nt.result()
        rc_nw, ex_nw = fut_news.result()
        if rc_nw != 0:
            print(f"[WARN] news_layer.py rc={rc_nw} ({ex_nw}) (non-blocking)", flush=True)
    w2_sec = round(time.time() - t_w2, 2)

    # Step 5: 严格零延迟 SLA 门禁校验 (任何滞后立即吼叫报警，绝不静默降级)
    if a_daily_max < latest_dt:
        errors.append(f"a_daily_lag({a_daily_max}<{latest_dt})")
    lhb_req_dt = prev_dt if (now.weekday() < 5 and 1500 <= hm < 1730 and latest_dt == today_s) else latest_dt
    for k in ("sh000002", "sz399107", "sh000300"):
        if idx_max.get(k, "") < latest_dt: errors.append(f"index_{k}_lag({idx_max.get(k)}<{latest_dt})")
    for sd in ("buy", "sell"):
        if lhb_max.get(sd, "") < lhb_req_dt: errors.append(f"lhb_{sd}_lag({lhb_max.get(sd)}<{lhb_req_dt})")
    if kpl_tape_max.get("kpl_merged_max", "") < latest_dt: errors.append(f"kpl_merged_lag({kpl_tape_max.get('kpl_merged_max')}<{latest_dt})")
    if kpl_tape_max.get("zt_micro_tape_max", "") < latest_dt: errors.append(f"zt_micro_tape_lag({kpl_tape_max.get('zt_micro_tape_max')}<{latest_dt})")

    c_pit = sqlite3.connect(f"file:{DATA_DIR}/cninfo_notices_5y_pit.db?mode=ro", uri=True)
    pit_max = (c_pit.execute("SELECT max(pub_datetime_cst) FROM notices").fetchone()[0] or "")[:19]
    c_pit.close()
    if pit_max[:10] < latest_dt: errors.append(f"cninfo_pit_lag({pit_max[:10]}<{latest_dt})")

    report = {
        "checked_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": round(time.time() - t0, 2),
        "wave1_sec": w1_sec,
        "wave2_sec": w2_sec,
        "status": "GREEN_ZERO_LAG" if not errors else "CRITICAL_LAG_ALERT",
        "latest_trade_date": latest_dt,
        "sources": {"a_daily": a_daily_max, "index_klines": idx_max, "lhb": lhb_max, **kpl_tape_max, "cninfo_pit_max": pit_max, "ir_qa_max": ir_max, "st_universe": st_sync},
        "caches": cache_status,
        "errors": errors,
    }
    os.makedirs(f"{SIM_DIR}/signals/pending", exist_ok=True)
    json.dump(report, open(f"{DATA_DIR}/rd_data_health_status.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(report, open(f"{SIM_DIR}/signals/pending/rd_premarket_ready.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[RD_MASTER_SYNC] status={report['status']} | latest_dt={latest_dt} | elapsed={report['elapsed_sec']}s (W1={w1_sec}s, W2={w2_sec}s) | errors={errors}", flush=True)
    urgent_p = f"{SIM_DIR}/signals/pending/URGENT_RD_DATA_ALERT.json"
    if errors:
        json.dump(report, open(urgent_p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        sys.exit(2)
    elif os.path.exists(urgent_p):
        os.remove(urgent_p)

if __name__ == "__main__":
    main()
