"""Python port of the level-generation core of the "mu +/- k*sigma/sqrt(dev)"
Pine Script indicator (see indicator/mu_k_sigma.pine), so the levels can be
replayed against historical 1-minute OHLCV outside of TradingView.

Only the math needed to *place* the upper/lower levels is ported here —
touch detection and reaction measurement live in volgen.reactions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class InstrumentParams:
    """Per-instrument constants the indicator auto-selects via isGC/isNQ/etc."""

    sigma_mult: float
    offset_pct: float
    ib_minutes: int
    fixed_offset: float | None = None  # NQ uses a hardcoded 15.75-pt offset


# Auto-detect table from the Pine script, GC row.
GC_PARAMS = InstrumentParams(sigma_mult=1.15, offset_pct=0.02, ib_minutes=30)


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

    idx = pd.to_datetime(df[ts_col], utc=False)
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
    """Load data/gvz_daily.csv -> Series of daily closes indexed by date."""
    df = pd.read_csv(path, parse_dates=["date"])
    return df.set_index("date")["close"].sort_index()


def _prior_session_close(gvz_close: pd.Series, session_date) -> float | None:
    """GVZ close from the most recent trading day strictly before `session_date`
    (mirrors `request.security(..., "D", close[1])`: prior bar, no lookahead).

    `gvz_close` is indexed by tz-naive calendar dates; `session_date` may be
    a tz-aware Timestamp, so compare on the date component only.
    """
    target = pd.Timestamp(session_date).tz_localize(None).normalize()
    prior = gvz_close[gvz_close.index < target]
    if prior.empty:
        return None
    return float(prior.iloc[-1])


def generate_levels(
    ohlcv_1m: pd.DataFrame,
    gvz_close: pd.Series,
    params: InstrumentParams = GC_PARAMS,
    rth_start: str = "09:30",
    rth_end: str = "16:00",
) -> pd.DataFrame:
    """Replay the indicator's per-session level placement over historical bars.

    Returns one row per session where the Initial Balance completed and all
    inputs were available (== the `ibJustDone and allReady` gate in Pine),
    with the upper/lower level values and the timestamp they "go live" at
    (the bar where the IB completes — when Pine draws the lines).
    """
    sessions = ohlcv_1m.between_time(rth_start, rth_end)
    rows = []

    for session_date, day_bars in sessions.groupby(sessions.index.date):
        if day_bars.empty:
            continue
        session_date = pd.Timestamp(session_date, tz=ohlcv_1m.index.tz)

        cash_open = float(day_bars["open"].iloc[0])

        vix_close = _prior_session_close(gvz_close, session_date)
        if vix_close is None:
            continue
        sigma_day = cash_open * (vix_close / 100.0) / math.sqrt(TRADING_DAYS_PER_YEAR)

        imp_up = cash_open + params.sigma_mult * sigma_day
        imp_dn = cash_open - params.sigma_mult * sigma_day

        # Pine updates ibH/ibL for the bar at exactly `ibStart + ibMins` *before*
        # checking `time - ibStart >= ibMins*60*1000` and setting ibDone — so
        # that bar's high/low IS included in the IB range (off-by-one if you
        # use a strict `<` cutoff here).
        ib_cutoff = day_bars.index[0] + pd.Timedelta(minutes=params.ib_minutes)
        ib_bars = day_bars[day_bars.index <= ib_cutoff]
        if ib_bars.empty:
            continue
        ib_high = float(ib_bars["high"].max())
        ib_low = float(ib_bars["low"].min())
        ib_range = ib_high - ib_low

        ib_ext_up = ib_high + ib_range
        ib_ext_dn = ib_low - ib_range

        sigma_offset = params.fixed_offset if params.fixed_offset is not None else sigma_day * params.offset_pct

        upper_level = (ib_ext_up + imp_up) / 2 - sigma_offset
        lower_level = (ib_ext_dn + imp_dn) / 2 + sigma_offset

        # First bar at/after the IB cutoff == the bar Pine flags `ibJustDone`.
        live_bars = day_bars[day_bars.index >= ib_cutoff]
        if live_bars.empty:
            continue
        created_at = live_bars.index[0]

        rows.append(
            {
                "session_date": session_date.date(),
                "created_at": created_at,
                "cash_open": cash_open,
                "vix_close": vix_close,
                "sigma_day": sigma_day,
                "imp_up": imp_up,
                "imp_dn": imp_dn,
                "ib_high": ib_high,
                "ib_low": ib_low,
                "ib_ext_up": ib_ext_up,
                "ib_ext_dn": ib_ext_dn,
                "sigma_offset": sigma_offset,
                "upper_level": upper_level,
                "lower_level": lower_level,
            }
        )

    return pd.DataFrame(rows)
