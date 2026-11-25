#!/usr/bin/env python3
"""
pick 席位公共量化与防错硬门禁库（2026-11-25 ALL-HANDS Phase 2 沉淀）
吸收 pick/astock/astock2/us/main/research 全员复盘核心铁律，代码级封死高频事故：
1. 分组最小样本与触发漂移硬锁 (防 P7 n=3 假显著 & B6 漂移)
2. 三连消融校验器：等均仓静态不动 + 零信号纯 1/vol + 剔除现金/美元垫子 (防 P6/B6)
3. yfinance 安全取价：强制 .dropna() 防早盘 NaN 占位 + 严禁 A 股代码 (防 U9/D12)
4. SEC 13F 金额单位量纲中位数单价自检 (防 U3 1000 倍误差)
5. 飞书跨席写前非空与 SHA256 防覆写锁 (防 P8)
"""
from __future__ import annotations
import hashlib
import re
from typing import Dict, Iterable, List, Optional, Tuple
import numpy as np
import pandas as pd


_ASHARE_RE = re.compile(r"^(\d{6}(\.(SS|SZ|BJ))?|(sh|sz)\d{6})$", re.IGNORECASE)


def check_group_balance(
    mask: pd.Series,
    min_group_n: int = 30,
    min_pct: float = 0.15,
    max_pct: float = 0.85,
    recent_tail_n: int = 60,
    max_drift_ratio: float = 3.0,
) -> Dict[str, object]:
    """Enforce min_group_n >= 30 and balanced trigger share (15%-85%) + drift audit."""
    s = mask.dropna().astype(bool)
    n_tot = int(len(s))
    n_true = int(s.sum())
    n_false = n_tot - n_true
    pct_true = (n_true / n_tot) if n_tot > 0 else 0.0
    ok_n = (n_true >= min_group_n) and (n_false >= min_group_n)
    ok_pct = (min_pct <= pct_true <= max_pct)

    drift_ok = True
    drift_ratio = 1.0
    if n_tot > recent_tail_n * 2:
        early_rate = float(s.iloc[:-recent_tail_n].mean())
        recent_rate = float(s.iloc[-recent_tail_n:].mean())
        lo, hi = min(early_rate, recent_rate), max(early_rate, recent_rate)
        drift_ratio = (hi / max(lo, 1e-4)) if hi > 0 else 1.0
        drift_ok = drift_ratio <= max_drift_ratio

    passed = bool(ok_n and ok_pct and drift_ok)
    return {
        "passed": passed,
        "n_total": n_tot,
        "n_true": n_true,
        "n_false": n_false,
        "pct_true": round(pct_true, 4),
        "ok_n": ok_n,
        "ok_pct": ok_pct,
        "drift_ratio": round(drift_ratio, 2),
        "drift_ok": drift_ok,
    }


def _perf_stats(r: pd.Series, rf: Optional[pd.Series] = None, periods_per_year: int = 12) -> Dict[str, float]:
    r = r.dropna()
    if len(r) < 6:
        return {"cagr": np.nan, "vol": np.nan, "sharpe": np.nan, "mdd": np.nan, "calmar": np.nan}
    eq = (1.0 + r).cumprod()
    yrs = len(r) / float(periods_per_year)
    cagr = float(eq.iloc[-1] ** (1.0 / yrs) - 1.0)
    vol = float(r.std(ddof=1) * np.sqrt(periods_per_year))
    ex = (r - rf.reindex(r.index).fillna(0.0)) if rf is not None else r
    sharpe = float((ex.mean() * periods_per_year) / (ex.std(ddof=1) * np.sqrt(periods_per_year) + 1e-12))
    mdd = float((eq / eq.cummax() - 1.0).min())
    calmar = float(cagr / abs(mdd)) if mdd < 0 else np.nan
    return {
        "cagr": round(cagr, 4),
        "vol": round(vol, 4),
        "sharpe": round(sharpe, 3),
        "mdd": round(mdd, 4),
        "calmar": round(calmar, 3) if np.isfinite(calmar) else np.nan,
    }


def run_triple_ablation(
    port_ret: pd.Series,
    weights_df: pd.DataFrame,
    asset_rets: pd.DataFrame,
    rf: Optional[pd.Series] = None,
    cash_cols: Optional[List[str]] = None,
    periods_per_year: int = 12,
) -> Dict[str, Dict[str, float]]:
    """
    三连消融照妖镜：
    1) strategy: 策略实盘净收益
    2) static_matched_avgw: 同样本期平均权重静态不动基线
    3) pure_inv_vol: 零信号纯 1/vol 风险平价基线（严格滞后 1 期）
    4) ex_cash_risk_only: 剔除现金/美元垫子后的纯风险资产重归一化收益
    """
    idx = port_ret.dropna().index.intersection(weights_df.index).intersection(asset_rets.index)
    w = weights_df.loc[idx].fillna(0.0)
    ar = asset_rets.loc[idx].fillna(0.0)
    rf_al = rf.reindex(idx).fillna(0.0) if rf is not None else None

    # 1. Static matched average weights
    avg_w = w.mean(axis=0)
    static_ret = (ar * avg_w).sum(axis=1)

    # 2. Pure 1/vol (causal 36-period rolling vol shifted by 1)
    vol = ar.rolling(min(36, max(12, periods_per_year * 3)), min_periods=periods_per_year).std().shift(1)
    inv_v = 1.0 / vol.replace(0.0, np.nan)
    inv_w = inv_v.div(inv_v.sum(axis=1), axis=0).fillna(1.0 / ar.shape[1])
    inv_vol_ret = (ar * inv_w).sum(axis=1)

    out = {
        "strategy": _perf_stats(port_ret.loc[idx], rf_al, periods_per_year),
        "static_matched_avgw": _perf_stats(static_ret, rf_al, periods_per_year),
        "pure_inv_vol": _perf_stats(inv_vol_ret, rf_al, periods_per_year),
    }

    # 3. Ex-cash / ex-USD pure risk assets
    if cash_cols:
        risk_cols = [c for c in w.columns if c not in set(cash_cols)]
        if risk_cols:
            w_r = w[risk_cols]
            w_r = w_r.div(w_r.sum(axis=1).replace(0.0, np.nan), axis=0).fillna(1.0 / len(risk_cols))
            ex_cash_ret = (ar[risk_cols] * w_r).sum(axis=1)
            out["ex_cash_risk_only"] = _perf_stats(ex_cash_ret, rf_al, periods_per_year)
    return out


def safe_yf_latest_close(tickers: Iterable[str]) -> Dict[str, Dict[str, object]]:
    """Fetch US/global latest close via yfinance with mandatory .dropna() and strict D12 A-share block."""
    import yfinance as yf

    out: Dict[str, Dict[str, object]] = {}
    for raw_t in tickers:
        t = str(raw_t).strip()
        if _ASHARE_RE.match(t):
            raise ValueError(f"D12 VIOLATION: yfinance strictly forbidden for A-share ticker {t!r}")
        tk = yf.Ticker(t)
        hist = tk.history(period="10d", auto_adjust=False)["Close"].dropna()
        if hist.empty:
            out[t] = {"ok": False, "price": None, "date": None}
            continue
        px = float(hist.iloc[-1])
        dt = str(hist.index[-1])[:10]
        fast_px = None
        try:
            fast_px = float(tk.fast_info.get("lastPrice"))
        except Exception:
            pass
        out[t] = {"ok": True, "price": round(px, 4), "date": dt, "fast_price": round(fast_px, 4) if fast_px else None}
    return out


def check_sec_13f_unit_scale(values: pd.Series, shares: pd.Series, ref_prices: pd.Series) -> Dict[str, object]:
    """Audit SEC 13F XML unit scale ($000 vs $1) via median implied price ratio."""
    df = pd.DataFrame({"v": values, "s": shares, "p": ref_prices}).dropna()
    df = df[(df["s"] > 0) & (df["p"] > 0)]
    if df.empty:
        return {"ok": False, "scale": "unknown", "median_ratio": None}
    implied = df["v"] / df["s"]
    ratio = float((implied / df["p"]).median())
    if 0.5 <= ratio <= 2.0:
        return {"ok": True, "scale": "USD_1", "median_ratio": round(ratio, 4)}
    if 0.0005 <= ratio <= 0.002:
        return {"ok": True, "scale": "USD_1000_NEED_X1000", "median_ratio": round(ratio, 6)}
    return {"ok": False, "scale": "ANOMALY", "median_ratio": round(ratio, 6)}


def check_feishu_overwrite_guard(raw_text: str, allow_overwrite: bool = False) -> Dict[str, object]:
    """Guard against accidental cross-seat overwrite on shared Feishu wiki nodes."""
    clean = (raw_text or "").strip()
    digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:16]
    has_body = len(clean) > 40
    blocked = bool(has_body and not allow_overwrite)
    return {"blocked": blocked, "chars": len(clean), "sha256": digest}


if __name__ == "__main__":
    # Built-in self-test
    rng = np.random.default_rng(42)
    # 1. Group balance catches n=3 failure & passes balanced mask
    bad_mask = pd.Series([True] * 633 + [False] * 3)
    good_mask = pd.Series(([True] * 3 + [False] * 7) * 60)
    r_bad = check_group_balance(bad_mask)
    r_good = check_group_balance(good_mask)
    assert not r_bad["passed"] and not r_bad["ok_n"], f"Failed catching n=3: {r_bad}"
    assert r_good["passed"], f"False reject on balanced mask: {r_good}"

    # 2. Triple ablation
    dates = pd.date_range("2010-01-31", periods=120, freq="ME")
    ar = pd.DataFrame({
        "SPX": rng.normal(0.01, 0.04, 120),
        "BOND": rng.normal(0.004, 0.02, 120),
        "USD": rng.normal(0.002, 0.01, 120),
    }, index=dates)
    w = pd.DataFrame({"SPX": 0.4, "BOND": 0.3, "USD": 0.3}, index=dates)
    pret = (ar * w).sum(axis=1)
    ab = run_triple_ablation(pret, w, ar, cash_cols=["USD"])
    assert "static_matched_avgw" in ab and "pure_inv_vol" in ab and "ex_cash_risk_only" in ab

    # 3. 13F unit scale
    u1 = check_sec_13f_unit_scale(pd.Series([100.0, 200.0]), pd.Series([1000.0, 2000.0]), pd.Series([100.0, 100.0]))
    assert u1["scale"] == "USD_1000_NEED_X1000", f"13F scale fail: {u1}"

    # 4. Feishu overwrite guard
    fg = check_feishu_overwrite_guard("03 全球大宗商品 已有2448字正式内容，严禁跨席清空覆盖" * 3, allow_overwrite=False)
    assert fg["blocked"] is True

    # 5. D12 A-share block
    try:
        safe_yf_latest_close(["600519.SS"])
        raise AssertionError("D12 guard did not raise")
    except ValueError:
        pass

    print("ALL 5 BACKTEST IRON GATES UNIT TESTS PASSED!")
