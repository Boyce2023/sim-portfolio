# /// script
# requires-python = ">=3.11"
# dependencies = ["yfinance>=0.2.40", "numpy>=1.24", "pandas>=2.0"]
# ///
"""
Market Regime Detection Module — Phase 1 (Rule-Based Layer)
============================================================
Implements the multi-factor rule layer from regime-detection-design.md.
No training data required. Reads VIX, yield curve, MA from yfinance.

Optionally writes regime state to:
  ~/.claude/nexus/truth/macro/regime.json

Usage:
  uv run --script scripts/regime_detection.py
  python scripts/regime_detection.py
  python scripts/regime_detection.py --update-nexus   # also write to Truth Store
  python scripts/regime_detection.py --quiet          # stdout only, no formatting
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

# ─── Paths ────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
NEXUS_ROOT = Path.home() / ".claude" / "nexus"
REGIME_JSON = NEXUS_ROOT / "truth" / "macro" / "regime.json"
INDICATORS_JSON = NEXUS_ROOT / "truth" / "macro" / "indicators.json"

# ─── Config import (optional — falls back to inline defaults) ─────────────────
sys.path.insert(0, str(SCRIPT_DIR))
try:
    from core.config import POD_TARGETS, REGIME_THRESHOLDS
    _SPY_CORRECTION_DRAWDOWN = float(REGIME_THRESHOLDS["CORRECTION"]["spy_drawdown_20d"])
    _SPY_BEAR_DRAWDOWN = float(REGIME_THRESHOLDS["BEAR"]["spy_drawdown_20d"])
except Exception:
    POD_TARGETS = None
    REGIME_THRESHOLDS = None
    _SPY_CORRECTION_DRAWDOWN = 0.05
    _SPY_BEAR_DRAWDOWN = 0.10

# ─── Enums & Data Classes ─────────────────────────────────────────────────────


class MarketRegime(str, Enum):
    BULL = "bull"
    SIDEWAYS = "sideways"
    CORRECTION = "correction"   # V6.2: SPY >5% drawdown from 20-day high
    BEAR = "bear"
    CRISIS = "crisis"


@dataclass
class RegimeSignal:
    regime: str          # MarketRegime.value
    confidence: float    # 0.0-1.0
    score: float         # weighted composite score (-1 to +1)
    signals: dict        # raw input signals used
    factor_scores: dict  # per-factor contribution
    timestamp: str
    source: str = "RuleBasedDetector v1.0 (Phase 1)"


# ─── Rule-Based Detector ──────────────────────────────────────────────────────


class RuleBasedDetector:
    """
    Multi-factor rule detector implementing Phase 1 of regime-detection-design.md.

    Factors and weights (design doc §2 推荐信号组合):
      VIX              35% — CBOE volatility index
      MA cross         25% — SPY 50MA / 200MA golden/death cross
      Yield curve      20% — 10Y-2Y spread (positive = steepening = bull)
      Credit spread    20% — HYG/LQD ratio 20-day change

    Crisis hard-trigger: VIX > 35, immediate regardless of other factors.
    """

    THRESHOLDS = {
        "vix_bull": 15.0,
        "vix_bear": 25.0,
        "vix_crisis": 35.0,
        "spread_10y2y_bull": 0.50,   # 50 bps
        "spread_10y2y_bear": 0.00,   # 0 bps (inversion)
        "hyg_lqd_change_bear": -0.02,
        "hyg_lqd_change_crisis": -0.05,
        "ma_buffer": 0.005,          # 0.5% buffer to reduce whipsaw
    }

    WEIGHTS = {
        "vix": 0.35,
        "ma_cross": 0.25,
        "yield_curve": 0.20,
        "credit_spread": 0.20,
    }

    # Score thresholds for regime classification
    BULL_THRESHOLD = 0.30
    BEAR_THRESHOLD = -0.30

    def detect(self, signals: dict) -> tuple[MarketRegime, float, dict]:
        """
        Classify regime from market signals.

        signals keys (all optional, defaults to neutral):
          vix              float — CBOE VIX index
          spy_50ma         float — SPY 50-day moving average
          spy_200ma        float — SPY 200-day moving average
          spread_10y2y     float — 10Y minus 2Y yield, in percentage points
          hyg_lqd_ratio    float — current HYG/LQD price ratio
          hyg_lqd_ratio_20d_ago  float — HYG/LQD ratio 20 trading days ago

        Returns: (MarketRegime, weighted_score, factor_scores_dict)
        """
        vix = signals.get("vix", 20.0)

        # Hard crisis trigger — no weighting needed
        if vix > self.THRESHOLDS["vix_crisis"]:
            factor_scores = {"vix": -2.0, "ma_cross": 0.0, "yield_curve": 0.0, "credit_spread": 0.0}
            return MarketRegime.CRISIS, -2.0, factor_scores

        factor_scores: dict[str, float] = {}

        # ── VIX factor ────────────────────────────────────────────────────────
        vix_bull = self.THRESHOLDS["vix_bull"]
        vix_bear = self.THRESHOLDS["vix_bear"]
        if vix < vix_bull:
            factor_scores["vix"] = 1.0
        elif vix > vix_bear:
            factor_scores["vix"] = -1.0
        else:
            # Linear interpolation: 15→25 maps 1→-1
            factor_scores["vix"] = 1.0 - 2.0 * (vix - vix_bull) / (vix_bear - vix_bull)

        # ── MA cross factor ───────────────────────────────────────────────────
        spy_50 = signals.get("spy_50ma")
        spy_200 = signals.get("spy_200ma")
        if spy_50 is not None and spy_200 is not None and spy_200 > 0:
            buf = self.THRESHOLDS["ma_buffer"]
            ratio = spy_50 / spy_200
            if ratio > 1.0 + buf:
                factor_scores["ma_cross"] = 1.0   # golden cross
            elif ratio < 1.0 - buf:
                factor_scores["ma_cross"] = -1.0  # death cross
            else:
                factor_scores["ma_cross"] = 0.0   # neutral band
        else:
            factor_scores["ma_cross"] = 0.0  # no data → neutral

        # ── Yield curve factor ────────────────────────────────────────────────
        spread = signals.get("spread_10y2y")
        if spread is not None:
            s_bull = self.THRESHOLDS["spread_10y2y_bull"]
            s_bear = self.THRESHOLDS["spread_10y2y_bear"]
            if spread > s_bull:
                factor_scores["yield_curve"] = 1.0
            elif spread < s_bear:
                factor_scores["yield_curve"] = -1.0
            else:
                # 0→50bps maps -1→1 relative to bull threshold
                factor_scores["yield_curve"] = spread / s_bull
        else:
            factor_scores["yield_curve"] = 0.0  # no data → neutral

        # ── Credit spread factor ──────────────────────────────────────────────
        hyg_lqd = signals.get("hyg_lqd_ratio")
        hyg_lqd_20d = signals.get("hyg_lqd_ratio_20d_ago")
        if hyg_lqd is not None and hyg_lqd_20d is not None and hyg_lqd_20d > 0:
            pct_change = (hyg_lqd - hyg_lqd_20d) / hyg_lqd_20d
            bear_thresh = self.THRESHOLDS["hyg_lqd_change_bear"]
            crisis_thresh = self.THRESHOLDS["hyg_lqd_change_crisis"]
            if pct_change > 0.01:
                factor_scores["credit_spread"] = 1.0
            elif pct_change < crisis_thresh:
                factor_scores["credit_spread"] = -2.0  # extreme credit stress
            elif pct_change < bear_thresh:
                factor_scores["credit_spread"] = -1.0
            else:
                # Interpolate between -1% and +1%
                factor_scores["credit_spread"] = pct_change / 0.01
        else:
            factor_scores["credit_spread"] = 0.0  # no data → neutral

        # ── Weighted composite score ──────────────────────────────────────────
        total_score = sum(
            factor_scores.get(k, 0.0) * w for k, w in self.WEIGHTS.items()
        )

        # ── Regime classification ─────────────────────────────────────────────
        if total_score > self.BULL_THRESHOLD:
            regime = MarketRegime.BULL
        elif total_score < self.BEAR_THRESHOLD:
            regime = MarketRegime.BEAR
        else:
            regime = MarketRegime.SIDEWAYS

        return regime, total_score, factor_scores


# ─── Transition Controller ────────────────────────────────────────────────────


class RegimeTransitionController:
    """
    Prevents noise-driven regime flapping.
    Crisis always switches immediately; other regimes require minimum hold days.
    Design doc §4.3 references RL-BHRP avg monthly turnover ~6%.
    """

    MIN_DAYS: dict[str, int] = {
        MarketRegime.BULL.value: 10,
        MarketRegime.SIDEWAYS.value: 5,
        MarketRegime.CORRECTION.value: 3,  # V6.2: fast-acting between NEUTRAL and BEAR
        MarketRegime.BEAR.value: 5,
        MarketRegime.CRISIS.value: 0,   # immediate
    }

    def should_switch(
        self,
        current_regime: str,
        new_regime: str,
        days_in_current: int,
    ) -> bool:
        if new_regime in (MarketRegime.CRISIS.value, MarketRegime.CORRECTION.value):
            # CORRECTION (like CRISIS) transitions immediately — drawdown is already
            # confirmed by SPY price, no anti-flap delay needed.
            return True
        min_days = self.MIN_DAYS.get(current_regime, 5)
        return days_in_current >= min_days


# ─── Data Fetching ────────────────────────────────────────────────────────────


def _try_load_nexus_macro() -> dict:
    """
    Attempt to load VIX and yield spreads from the Nexus Truth Store
    (already refreshed by sync_nexus.py). Falls back to yfinance if missing.
    """
    if not INDICATORS_JSON.exists():
        return {}
    try:
        with INDICATORS_JSON.open() as f:
            data = json.load(f)
        out: dict = {}
        for ind in data.get("indicators", []):
            entity = ind.get("entity", "")
            value = ind.get("value")
            if entity == "VIX" and value is not None:
                out["vix"] = float(value)
            elif entity == "US10Y" and value is not None:
                out["us10y"] = float(value)
            elif entity == "US2Y" and value is not None:
                out["us2y"] = float(value)
        if "us10y" in out and "us2y" in out:
            out["spread_10y2y"] = out["us10y"] - out["us2y"]
        return out
    except Exception:
        return {}


def fetch_market_signals(verbose: bool = True) -> dict:
    """
    Build the signals dict for the RuleBasedDetector.
    Priority: Nexus Truth Store (already fresh) → yfinance live fetch.
    """
    try:
        import yfinance as yf
    except ImportError:
        print("[regime_detection] yfinance not available, using Nexus cache only", file=sys.stderr)
        yf = None

    signals: dict = {}

    # ── VIX and yield curve from Nexus Truth Store ───────────────────────────
    nexus = _try_load_nexus_macro()
    if "vix" in nexus:
        signals["vix"] = nexus["vix"]
        if verbose:
            print(f"  VIX (Nexus):  {signals['vix']:.2f}")
    elif yf is not None:
        try:
            vix_ticker = yf.Ticker("^VIX")
            vix_info = vix_ticker.fast_info
            signals["vix"] = float(vix_info.last_price)
            if verbose:
                print(f"  VIX (live):   {signals['vix']:.2f}")
        except Exception as e:
            if verbose:
                print(f"  VIX: fetch failed ({e}), defaulting to 20.0", file=sys.stderr)
            signals["vix"] = 20.0

    if "spread_10y2y" in nexus:
        signals["spread_10y2y"] = nexus["spread_10y2y"]
        if verbose:
            print(f"  10Y-2Y (Nexus): {signals['spread_10y2y']:.3f}%")

    # ── SPY moving averages + 20-day high from yfinance ──────────────────────
    if yf is not None:
        try:
            spy = yf.download("SPY", period="1y", auto_adjust=True, progress=False)
            if not spy.empty:
                close = spy["Close"].squeeze()
                signals["spy_50ma"] = float(close.iloc[-50:].mean()) if len(close) >= 50 else None
                signals["spy_200ma"] = float(close.iloc[-200:].mean()) if len(close) >= 200 else None
                if signals.get("spy_50ma") and verbose:
                    print(f"  SPY 50MA:  {signals['spy_50ma']:.2f}")
                    print(f"  SPY 200MA: {signals['spy_200ma']:.2f}")

                # V6.2: 20-day high for CORRECTION / BEAR drawdown check
                signals["spy_current"] = float(close.iloc[-1])
                if len(close) >= 20:
                    signals["spy_20d_high"] = float(close.iloc[-20:].max())
                    drawdown = (signals["spy_20d_high"] - signals["spy_current"]) / signals["spy_20d_high"]
                    signals["spy_drawdown_from_20d_high"] = round(drawdown, 6)
                    if verbose:
                        print(f"  SPY current:  {signals['spy_current']:.2f}")
                        print(f"  SPY 20d high: {signals['spy_20d_high']:.2f}  (drawdown {drawdown*100:+.2f}%)")
        except Exception as e:
            if verbose:
                print(f"  SPY MA: fetch failed ({e}), skipping", file=sys.stderr)

    # ── HYG/LQD credit spread from yfinance ──────────────────────────────────
    if yf is not None:
        try:
            etfs = yf.download(["HYG", "LQD"], period="2mo", auto_adjust=True, progress=False)
            hyg_close = etfs["Close"]["HYG"].dropna()
            lqd_close = etfs["Close"]["LQD"].dropna()
            common_idx = hyg_close.index.intersection(lqd_close.index)
            if len(common_idx) >= 22:
                ratio_series = hyg_close.loc[common_idx] / lqd_close.loc[common_idx]
                signals["hyg_lqd_ratio"] = float(ratio_series.iloc[-1])
                signals["hyg_lqd_ratio_20d_ago"] = float(ratio_series.iloc[-21])
                if verbose:
                    pct = (signals["hyg_lqd_ratio"] - signals["hyg_lqd_ratio_20d_ago"]) / signals["hyg_lqd_ratio_20d_ago"] * 100
                    print(f"  HYG/LQD 20d chg: {pct:+.2f}%")
        except Exception as e:
            if verbose:
                print(f"  HYG/LQD: fetch failed ({e}), skipping", file=sys.stderr)

    return signals


# ─── Nexus Integration ────────────────────────────────────────────────────────

PORTFOLIO_WEIGHTS = {
    MarketRegime.BULL.value: {
        "equity_pct": [0.60, 0.80],
        "cash_pct": [0.20, 0.40],
        "allow_short": False,
        "allow_new_position": True,
        "note": "趋势跟随，轻仓做空",
    },
    MarketRegime.SIDEWAYS.value: {
        "equity_pct": [0.40, 0.60],
        "cash_pct": [0.40, 0.60],
        "allow_short": True,
        "allow_new_position": "cautious",
        "note": "区间操作，做多做空均可",
    },
    MarketRegime.CORRECTION.value: {
        # V6.2: Pod I halved, Pod III = 0%, cash ≥ 20%
        # Equity range derived from POD_TARGETS["CORRECTION"]: I=12.5% + II=17.5% = 30%
        "equity_pct": [0.25, 0.40],
        "cash_pct": [0.20, 0.40],
        "allow_short": True,
        "allow_new_position": "cautious",
        "note": "SPY>5%回撤，Pod I减半，Pod III清零，现金≥20%",
        "pod_targets": (
            {k: v for k, v in POD_TARGETS["CORRECTION"].items()}
            if POD_TARGETS is not None
            else {"I": 0.125, "II": 0.175, "III": 0.00, "IV": 0.00, "CASH": 0.20}
        ),
    },
    MarketRegime.BEAR.value: {
        "equity_pct": [0.20, 0.40],
        "cash_pct": [0.60, 0.80],
        "allow_short": True,
        "allow_new_position": False,
        "note": "防守为主，鼓励对冲",
    },
    MarketRegime.CRISIS.value: {
        "equity_pct": [0.00, 0.20],
        "cash_pct": [0.80, 1.00],
        "allow_short": False,
        "allow_new_position": False,
        "note": "极端风控，现金为王",
    },
}


def write_regime_to_nexus(signal: RegimeSignal) -> None:
    """Write regime state to ~/.claude/nexus/truth/macro/regime.json."""
    if not REGIME_JSON.parent.exists():
        print(f"[regime_detection] Nexus truth/macro/ not found at {REGIME_JSON.parent}", file=sys.stderr)
        return

    # Load existing to preserve days_in_regime counter
    existing: dict = {}
    if REGIME_JSON.exists():
        try:
            existing = json.loads(REGIME_JSON.read_text())
        except Exception:
            pass

    prev_regime = existing.get("current_regime", {}).get("regime", "")
    prev_since = existing.get("current_regime", {}).get("since_date", signal.timestamp[:10])
    prev_days = existing.get("current_regime", {}).get("days_in_regime", 0)

    if signal.regime == prev_regime:
        since_date = prev_since
        days_in_regime = prev_days + 1
    else:
        since_date = signal.timestamp[:10]
        days_in_regime = 0

    payload = {
        "schema_version": "1.1",
        "entity": "market_regime",
        "category": "macro",
        "last_updated": signal.timestamp,
        "current_regime": {
            "regime": signal.regime,
            "confidence": round(signal.confidence, 4),
            "score": round(signal.score, 4),
            "rule_based": signal.regime,
            "hmm_based": None,
            "since_date": since_date,
            "days_in_regime": days_in_regime,
            "source": signal.source,
            "source_date": signal.timestamp[:10],
            "confidence_level": "medium",
            "verified": True,
        },
        "signals_snapshot": signal.signals,
        "factor_scores": signal.factor_scores,
        "portfolio_guidance": PORTFOLIO_WEIGHTS[signal.regime],
        "stale_after_days": 1,
        "yf_command": "python3 scripts/regime_detection.py --update-nexus",
    }

    REGIME_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"[regime_detection] Written → {REGIME_JSON}")


# ─── Confidence Mapping ───────────────────────────────────────────────────────


def score_to_confidence(score: float) -> float:
    """Map weighted score magnitude to a confidence value (0.5-0.95)."""
    abs_score = abs(score)
    if abs_score >= 1.5:
        return 0.95   # crisis
    if abs_score >= 0.6:
        return 0.80
    if abs_score >= 0.3:
        return 0.70
    return 0.55       # near neutral boundary, lower confidence


# ─── Main ─────────────────────────────────────────────────────────────────────


def run(update_nexus: bool = False, quiet: bool = False) -> RegimeSignal:
    verbose = not quiet
    tz_utc8 = timezone(timedelta(hours=8))
    now_iso = datetime.now(tz_utc8).isoformat()

    if verbose:
        print("=" * 60)
        print("  Market Regime Detection — Phase 1 (Rule-Based Layer)")
        print("=" * 60)
        print(f"  Timestamp: {now_iso}")
        print()
        print("  [1/3] Fetching market signals...")

    signals = fetch_market_signals(verbose=verbose)

    if verbose:
        print()
        print("  [2/3] Running rule-based detector...")

    detector = RuleBasedDetector()
    regime, score, factor_scores = detector.detect(signals)
    confidence = score_to_confidence(score)

    # ── V6.2: SPY drawdown override (CORRECTION sits between NEUTRAL and BEAR) ─
    # Applied AFTER the rule-based score, so it can override SIDEWAYS→CORRECTION
    # or BEAR→CORRECTION (when drawdown is between 5-10%).
    spy_drawdown = signals.get("spy_drawdown_from_20d_high")
    drawdown_override: Optional[str] = None
    if spy_drawdown is not None and regime != MarketRegime.CRISIS:
        if spy_drawdown > _SPY_BEAR_DRAWDOWN:
            # >10% drawdown forces BEAR regardless of rule-based score
            if regime != MarketRegime.BEAR:
                drawdown_override = MarketRegime.BEAR.value
                regime = MarketRegime.BEAR
        elif spy_drawdown > _SPY_CORRECTION_DRAWDOWN:
            # 5-10% drawdown: force CORRECTION if rule-based says BULL or SIDEWAYS
            # (don't downgrade BEAR to CORRECTION)
            if regime in (MarketRegime.BULL, MarketRegime.SIDEWAYS):
                drawdown_override = MarketRegime.CORRECTION.value
                regime = MarketRegime.CORRECTION

    if verbose and drawdown_override:
        print(f"  [V6.2] SPY drawdown override → {drawdown_override.upper()}"
              f"  (drawdown={spy_drawdown*100:.2f}%)")

    signal = RegimeSignal(
        regime=regime.value,
        confidence=confidence,
        score=score,
        signals=signals,
        factor_scores={k: round(v, 4) for k, v in factor_scores.items()},
        timestamp=now_iso,
    )

    if verbose:
        print()
        print("  [3/3] Results")
        print("  " + "-" * 56)
        print(f"  Regime:     {signal.regime.upper()}")
        print(f"  Score:      {signal.score:+.4f}  (Bull>0.3 / Bear<-0.3 / Crisis=-2.0)")
        print(f"  Confidence: {signal.confidence:.0%}")
        if drawdown_override:
            print(f"  Override:   SPY 20d drawdown {spy_drawdown*100:.2f}% → forced {drawdown_override.upper()}")
        print()
        print("  Factor breakdown:")
        w = RuleBasedDetector.WEIGHTS
        for factor, fscore in factor_scores.items():
            weight = w.get(factor, 0)
            contrib = fscore * weight
            print(f"    {factor:<18}  raw={fscore:+.3f}  wt={weight:.0%}  contrib={contrib:+.4f}")
        print()
        guidance = PORTFOLIO_WEIGHTS[signal.regime]
        print(f"  Portfolio guidance ({signal.regime}):")
        print(f"    Equity:      {guidance['equity_pct'][0]*100:.0f}–{guidance['equity_pct'][1]*100:.0f}%")
        print(f"    Cash:        {guidance['cash_pct'][0]*100:.0f}–{guidance['cash_pct'][1]*100:.0f}%")
        print(f"    Allow short: {guidance['allow_short']}")
        print(f"    New longs:   {guidance['allow_new_position']}")
        print(f"    Note:        {guidance['note']}")
        if "pod_targets" in guidance:
            pt = guidance["pod_targets"]
            print(f"    Pod targets: I={pt.get('I',0)*100:.1f}%  II={pt.get('II',0)*100:.1f}%"
                  f"  III={pt.get('III',0)*100:.1f}%  CASH={pt.get('CASH',0)*100:.1f}%")
        print()

    if update_nexus:
        write_regime_to_nexus(signal)
    else:
        # Always print JSON to stdout for piping/capture
        if quiet:
            print(json.dumps(asdict(signal), ensure_ascii=False))

    # ── V6.2: Emit cross-market signal if regime changed ─────────────────────
    try:
        prev_regime = ""
        if REGIME_JSON.exists():
            try:
                prev_data = json.loads(REGIME_JSON.read_text())
                prev_regime = prev_data.get("current_regime", {}).get("regime", "")
            except Exception:
                pass

        if signal.regime != prev_regime:
            try:
                from cross_intel import emit_regime_signal
                spy_change = signals.get("spy_drawdown_from_20d_high")
                # Use drawdown as a signed change (negative = drop)
                spy_change_pct = -(spy_change * 100) if spy_change is not None else 0.0
                sig_path = emit_regime_signal(signal.regime, spy_change_pct)
                if verbose:
                    print(f"  [Nexus signal] Regime changed {prev_regime} → {signal.regime.upper()}")
                    print(f"  [Nexus signal] Written → {sig_path}")
            except ImportError:
                pass  # cross_intel.py not available — signal emission skipped
    except Exception:
        pass  # signal emission is best-effort; never break the main flow

    return signal


def main() -> None:
    parser = argparse.ArgumentParser(description="Market Regime Detection — Phase 1 rule-based layer")
    parser.add_argument(
        "--update-nexus",
        action="store_true",
        help="Write regime state to ~/.claude/nexus/truth/macro/regime.json",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress formatted output; print JSON result to stdout",
    )
    args = parser.parse_args()
    run(update_nexus=args.update_nexus, quiet=args.quiet)


if __name__ == "__main__":
    main()
