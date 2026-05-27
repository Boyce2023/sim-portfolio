"""Unified portfolio data access. All scripts use this instead of raw json.load().

Usage:
    from scripts.core.portfolio import load_state, save_state, reload_state

    state = load_state()
    acct = state.account("a_share")
    print(acct.cash, acct.total_assets)
    pos = acct.position_by_ticker("002028")

    state.add_trade({...})
    save_state(state)
"""

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Optional

REPO_DIR = Path(__file__).parent.parent.parent  # sim-portfolio/
DEFAULT_PATH = REPO_DIR / "portfolio_state.json"

# ---------------------------------------------------------------------------
# Module-level cache: (path_str, mtime_ns, load_time) -> PortfolioState
# ---------------------------------------------------------------------------
_cache: dict[str, tuple[float, "PortfolioState"]] = {}
_CACHE_TTL_SECONDS = 1.0


class AccountView:
    """Typed view over one account section (a_share or us).

    Wraps the underlying dict directly — mutations propagate to save_state()
    without needing to copy data out and back in.
    """

    def __init__(self, data: dict) -> None:
        self._data = data

    # ------------------------------------------------------------------
    # Core numeric fields
    # ------------------------------------------------------------------

    @property
    def cash(self) -> float:
        return float(self._data.get("cash", 0.0))

    @property
    def initial_capital(self) -> float:
        return float(self._data.get("initial_capital", 0.0))

    @property
    def total_assets(self) -> float:
        return float(self._data.get("total_assets", 0.0))

    @property
    def realized_pnl(self) -> float:
        return float(self._data.get("realized_pnl", 0.0))

    @property
    def unrealized_pnl(self) -> float:
        return float(self._data.get("unrealized_pnl", 0.0))

    @property
    def currency(self) -> str:
        return str(self._data.get("currency", ""))

    # ------------------------------------------------------------------
    # Derived metrics
    # ------------------------------------------------------------------

    @property
    def return_pct(self) -> float:
        """Total return % vs initial capital."""
        ic = self.initial_capital
        if ic == 0:
            return 0.0
        return round((self.total_assets - ic) / ic * 100, 4)

    @property
    def cash_pct(self) -> float:
        """Cash as fraction of total assets (0-1). Prefers stored value."""
        stored = self._data.get("cash_pct")
        if stored is not None:
            return float(stored)
        ta = self.total_assets
        if ta == 0:
            return 0.0
        return round(self.cash / ta, 4)

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    @property
    def positions(self) -> list[dict]:
        """Long positions list (direct reference — mutations propagate)."""
        return self._data.setdefault("positions", [])

    @property
    def short_positions(self) -> list[dict]:
        """Short positions list (direct reference)."""
        return self._data.setdefault("short_positions", [])

    def position_by_ticker(self, ticker: str) -> Optional[dict]:
        """Return the first long position matching ticker, or None."""
        ticker = ticker.upper()
        for pos in self.positions:
            if str(pos.get("ticker", "")).upper() == ticker:
                return pos
        return None

    def short_position_by_ticker(self, ticker: str) -> Optional[dict]:
        """Return the first short position matching ticker, or None."""
        ticker = ticker.upper()
        for pos in self.short_positions:
            if str(pos.get("ticker", "")).upper() == ticker:
                return pos
        return None

    # ------------------------------------------------------------------
    # Escape hatch
    # ------------------------------------------------------------------

    @property
    def raw(self) -> dict:
        """Underlying dict — for advanced/schema-specific access."""
        return self._data

    def __repr__(self) -> str:
        return (
            f"AccountView(currency={self.currency!r}, "
            f"cash={self.cash:,.2f}, total_assets={self.total_assets:,.2f}, "
            f"positions={len(self.positions)}, shorts={len(self.short_positions)})"
        )


class PortfolioState:
    """Typed wrapper over portfolio_state.json.

    The wrapper holds a direct reference to the parsed dict, so AccountView
    mutations are reflected when save_state() is called.
    """

    def __init__(self, data: dict) -> None:
        self._data = data

    # ------------------------------------------------------------------
    # Account access
    # ------------------------------------------------------------------

    def account(self, name: str) -> AccountView:
        """Return AccountView for 'a_share' or 'us'.

        Raises KeyError if the account section is missing.
        """
        accounts = self._data.get("accounts", {})
        if name not in accounts:
            raise KeyError(
                f"Account {name!r} not found. Available: {list(accounts.keys())}"
            )
        return AccountView(accounts[name])

    # ------------------------------------------------------------------
    # Top-level sections
    # ------------------------------------------------------------------

    @property
    def trade_log(self) -> list[dict]:
        """Trade log list (direct reference)."""
        return self._data.setdefault("trade_log", [])

    @property
    def meta(self) -> dict:
        """_meta section."""
        return self._data.get("_meta", {})

    @property
    def performance(self) -> dict:
        """performance section."""
        return self._data.get("performance", {})

    @property
    def pending_actions(self) -> dict:
        """pending_orders list (returned as dict wrapper for API symmetry).

        The raw list is available via .pending_actions['orders'].
        """
        orders = self._data.get("pending_orders", [])
        return {"orders": orders}

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add_trade(self, entry: dict) -> None:
        """Append a trade entry to trade_log."""
        self.trade_log.append(entry)

    # ------------------------------------------------------------------
    # Escape hatch
    # ------------------------------------------------------------------

    @property
    def raw(self) -> dict:
        """Full underlying dict — direct access for schema-specific fields."""
        return self._data

    def __repr__(self) -> str:
        meta = self.meta
        return (
            f"PortfolioState(version={meta.get('version')!r}, "
            f"last_updated={meta.get('last_updated')!r}, "
            f"trade_log_entries={len(self.trade_log)})"
        )


# ---------------------------------------------------------------------------
# Load / Save / Reload
# ---------------------------------------------------------------------------

def load_state(path: Optional[Path] = None) -> PortfolioState:
    """Load portfolio state with 1-second TTL caching.

    Same-second loads return the cached instance (no disk re-read). This is
    safe for single-process scripts; the cache is per-interpreter.
    """
    resolved = Path(path) if path is not None else DEFAULT_PATH
    key = str(resolved)
    now = time.monotonic()

    if key in _cache:
        cached_time, cached_state = _cache[key]
        if now - cached_time < _CACHE_TTL_SECONDS:
            return cached_state

    with open(resolved, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    state = PortfolioState(data)
    _cache[key] = (now, state)
    return state


def save_state(state: PortfolioState, path: Optional[Path] = None) -> None:
    """Atomic write: write to tempfile then os.replace to avoid corruption.

    Invalidates the cache for the target path so the next load_state() call
    reads the freshly written file.
    """
    resolved = Path(path) if path is not None else DEFAULT_PATH
    dir_ = resolved.parent

    fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state.raw, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, resolved)
    except Exception:
        # Clean up temp file on failure; let the exception propagate
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    # Invalidate cache so next load_state() sees the new file
    _cache.pop(str(resolved), None)


def reload_state(path: Optional[Path] = None) -> PortfolioState:
    """Force cache invalidation and reload from disk."""
    resolved = Path(path) if path is not None else DEFAULT_PATH
    _cache.pop(str(resolved), None)
    return load_state(resolved)
