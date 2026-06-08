"""Daily ATR (Wilder's, period=14 by default), built from the continuous 1m
series aggregated to daily bars — used to scale fade-trade TP/SL to the
prevailing volatility regime instead of fixed point values.

No-lookahead by construction: `atr_as_of(session_date)` only ever returns the
ATR computed through the session strictly before `session_date` (mirrors
`_prior_session_close` in volgen.levels — same "prior bar" pattern as
`request.security(..., "D", ta.atr(14)[1])`).
"""
from __future__ import annotations

import pandas as pd


def daily_ohlc(ohlcv_1m: pd.DataFrame) -> pd.DataFrame:
    """Aggregate the (tz-aware, RTH-and-overnight) 1m series into one OHLC bar
    per calendar session date."""
    daily = ohlcv_1m.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last"})
    return daily.dropna(subset=["open"])


def wilder_atr(daily: pd.DataFrame, period: int = 14) -> pd.Series:
    """Classic Wilder ATR: true range smoothed with an alpha=1/period EMA
    (`ta.atr` in Pine uses `ta.rma`, which is exactly this)."""
    high, low, close = daily["high"], daily["low"], daily["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()


def build_atr_lookup(ohlcv_1m: pd.DataFrame, period: int = 14) -> pd.Series:
    """Returns a Series indexed by tz-naive calendar date -> ATR value, ready
    for `atr_as_of`."""
    daily = daily_ohlc(ohlcv_1m)
    atr = wilder_atr(daily, period=period)
    atr.index = pd.DatetimeIndex(atr.index).tz_localize(None).normalize()
    return atr.dropna()


def atr_as_of(atr_lookup: pd.Series, session_date) -> float | None:
    """ATR from the most recent session strictly before `session_date` — no
    lookahead, same convention as `_prior_session_close`."""
    target = pd.Timestamp(session_date).tz_localize(None).normalize()
    prior = atr_lookup[atr_lookup.index < target]
    if prior.empty:
        return None
    return float(prior.iloc[-1])
