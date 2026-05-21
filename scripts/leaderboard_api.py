"""
leaderboard_api.py
==================
Patch instructions for scripts/api_server.py to add three new endpoints:

  GET /leaderboard              — Full leaderboard HTML page
  GET /api/v1/leaderboard/data  — Raw JSON metrics (for external embedding)
  GET /api/v1/leaderboard/csv   — CSV download of full trade history

HOW TO INTEGRATE
----------------
1. Copy leaderboard_page.py into scripts/leaderboard_page.py
2. In scripts/api_server.py:
   a. Add the import at the top (after existing imports):

       from leaderboard_page import make_leaderboard_page, _compute_leaderboard_metrics, make_csv_trade_log

   b. In APIHandler.do_GET(), add three new elif blocks BEFORE the final else clause:

       elif path == "/leaderboard":
           sim = load_sim_portfolio()
           if sim:
               self._html(make_leaderboard_page(sim))
           else:
               self._html("<p style='color:#f85149'>Portfolio data unavailable</p>", 500)

       elif path == "/api/v1/leaderboard/data":
           sim = load_sim_portfolio()
           if sim:
               self._json(_compute_leaderboard_metrics(sim))
           else:
               self._json({"error": "portfolio data not found"}, 500)

       elif path == "/api/v1/leaderboard/csv":
           sim = load_sim_portfolio()
           if sim:
               csv_data = make_csv_trade_log(sim)
               self.send_response(200)
               self.send_header("Content-Type", "text/csv; charset=utf-8")
               self.send_header("Content-Disposition", 'attachment; filename="nexus_trades.csv"')
               self._cors()
               self.end_headers()
               self.wfile.write(csv_data.encode("utf-8"))
           else:
               self._json({"error": "portfolio data not found"}, 500)

   c. Update /docs to include the new endpoints (optional but recommended):

       <div class="endpoint"><code>GET</code> <a href="/leaderboard">/leaderboard</a> — Public performance leaderboard page</div>
       <div class="endpoint"><code>GET</code> <a href="/api/v1/leaderboard/data">/api/v1/leaderboard/data</a> — Leaderboard metrics JSON</div>
       <div class="endpoint"><code>GET</code> <a href="/api/v1/leaderboard/csv">/api/v1/leaderboard/csv</a> — Trade history CSV download</div>

3. Commit and push to Railway — no new pip dependencies needed.


BENCHMARK DATA (benchmark_snapshots)
--------------------------------------
The leaderboard reads sim["benchmark_snapshots"] — a list of dicts:
  [{"date": "YYYY-MM-DD", "spy_return_pct": float, "qqq_return_pct": float, "csi300_return_pct": float}, ...]

This field does NOT exist in the current sim-portfolio.json.

Two options:
  A. Manual update: add benchmark_snapshots to sim-portfolio.json whenever you
     update daily_snapshots. Values = cumulative % return from start date.
     Example for May 18-21 (approximate):
     [
       {"date": "2026-05-18", "spy_return_pct": 0.3,  "qqq_return_pct": 0.5,  "csi300_return_pct": 0.2},
       {"date": "2026-05-19", "spy_return_pct": -0.1, "qqq_return_pct": -0.2, "csi300_return_pct": 0.1},
       {"date": "2026-05-20", "spy_return_pct": 0.8,  "qqq_return_pct": 1.1,  "csi300_return_pct": 0.6},
       {"date": "2026-05-21", "spy_return_pct": 0.4,  "qqq_return_pct": 0.6,  "csi300_return_pct": 0.5}
     ]

  B. Auto-fetch via yfinance: add a background thread in api_server.py that
     fetches SPY/QQQ/000300.SS history and writes to sim-portfolio.json.
     See auto_benchmark_fetch() stub below.


RATIONALE FIELD IN trade_log
------------------------------
The leaderboard displays t["rationale"] for each trade.
Current trade_log entries don't have this field.

Add it to sim-portfolio.json trade_log entries:
  {"date": "2026-05-18", "account": "us", "action": "buy",
   "ticker": "NVDA", "shares": 80, "price": 225.0,
   "rationale": "AI芯片底仓，CUDA锁定+Jevons悖论验证"}

If missing, the field defaults to "" (blank in the table), which is fine.


AUTO BENCHMARK FETCH STUB
--------------------------
Add this function to api_server.py and call it in a background thread on startup:

    def _refresh_benchmark_snapshots():
        \"\"\"Fetch SPY/QQQ cumulative returns since sim start and update sim-portfolio.json.\"\"\"
        if not HAS_YF:
            return
        try:
            import yfinance as yf
            sim = load_sim_portfolio()
            if not sim:
                return
            start = sim["meta"]["start_date"]
            tickers = {"spy": "SPY", "qqq": "QQQ", "csi300": "000300.SS"}
            hist = {}
            for key, ticker in tickers.items():
                h = yf.download(ticker, start=start, progress=False)["Close"]
                if not h.empty:
                    base = float(h.iloc[0])
                    hist[key] = {str(d.date()): round((float(p) / base - 1) * 100, 2)
                                 for d, p in h.items()}
            dates = sorted(set().union(*[set(v.keys()) for v in hist.values()]))
            bench_snaps = []
            for d in dates:
                bench_snaps.append({
                    "date": d,
                    "spy_return_pct":    hist.get("spy",    {}).get(d, 0),
                    "qqq_return_pct":    hist.get("qqq",    {}).get(d, 0),
                    "csi300_return_pct": hist.get("csi300", {}).get(d, 0),
                })
            sim["benchmark_snapshots"] = bench_snaps
            with open(SIM_PORTFOLIO, "w") as fp:
                json.dump(sim, fp, ensure_ascii=False, indent=2)
            print(f"[benchmark] refreshed {len(bench_snaps)} snapshots")
        except Exception as e:
            print(f"[benchmark] refresh failed: {e}")

    # In __main__:
    threading.Thread(target=_refresh_benchmark_snapshots, daemon=True).start()
"""

# This file is documentation-only (no executable code outside the docstring).
# The actual implementation is in leaderboard_page.py.
