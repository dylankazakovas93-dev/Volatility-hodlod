"""Data loading utilities for 1-minute OHLCV bars and daily volatility-index
closes. Split out of the original volgen/levels.py verbatim (no logic
changes) so data loading and level-placement math live in separate,
single-purpose modules.
"""
from __future__ import annotations

import pandas as pd


def load_1m_ohlcv(path: str, tz: str = "America/New_York") -> pd.DataFrame:
    """Load a 1-minute OHLCV CSV into a tz-aware DataFrame indexed by time.

    Expects a timestamp-like column (any of: timestamp, datetime, date, time)
    plus open/high/low/close[/volume]. Column names are matched case-insensitively.
    Naive timestamps are assumed to already be in `tz` (the exchange's local time);
    tz-aware timestamps are converted to `tz`.
    """
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}

    ts_col = next((cols[c] for c in ("timestamp", "datetime", "date", "time") if c in cols), None)
    if ts_col is None:
        raise ValueError(f"no timestamp column found in {path}; have {list(df.columns)}")

    try:
        idx = pd.to_datetime(df[ts_col], utc=False)
    except ValueError as exc:
        if "Mixed timezones" not in str(exc):
            raise
        idx = pd.to_datetime(df[ts_col], utc=True)
    if idx.dt.tz is None:
        idx = idx.dt.tz_localize(tz)
    else:
        idx = idx.dt.tz_convert(tz)

    # NOTE: use .to_numpy() (not the bare Series) for the column data — passing
    # Series with their original RangeIndex alongside an explicit `index=` makes
    # pandas align on labels, and since a RangeIndex never matches a
    # DatetimeIndex, every value silently becomes NaN.
    out = pd.DataFrame(
        {
            "open": df[cols["open"]].astype(float).to_numpy(),
            "high": df[cols["high"]].astype(float).to_numpy(),
            "low": df[cols["low"]].astype(float).to_numpy(),
            "close": df[cols["close"]].astype(float).to_numpy(),
        },
        index=idx,
    )
    if "volume" in cols:
        out["volume"] = df[cols["volume"]].astype(float).to_numpy()

    out = out.sort_index()
    out.index.name = "time"
    return out


def load_gvz_daily(path: str) -> pd.Series:
    """Load a daily-close CSV (date, ..., close) -> Series of daily closes
    indexed by date. Used for both GVZ (GC) and VXN (NQ) daily vol inputs —
    the loader is generic; the file passed in determines which index it is."""
    df = pd.read_csv(path, parse_dates=["date"])
    return df.set_index("date")["close"].sort_index()


def prior_session_close(vol_close: pd.Series, session_date) -> float | None:
    """Daily-close value from the most recent trading day strictly before
    `session_date` (mirrors `request.security(..., "D", close[1])`: prior
    bar, no lookahead).

    `vol_close` is indexed by tz-naive calendar dates; `session_date` may be
    a tz-aware Timestamp, so compare on the date component only.
    """
    target = pd.Timestamp(session_date).tz_localize(None).normalize()
    prior = vol_close[vol_close.index < target]
    if prior.empty:
        return None
    return float(prior.iloc[-1])
