"""Level-placement math ported from the "mu +/- k*sigma/sqrt(dev)" Pine
Script indicator. Split out of the original volgen/levels.py verbatim (no
logic changes) — this module is the level-generation half; data loading
lives in src/data_loader.py.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from src.data_loader import prior_session_close

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class InstrumentParams:
    """Per-instrument constants the indicator auto-selects via isGC/isNQ/etc."""

    sigma_mult: float
    offset_pct: float
    ib_minutes: int
    fixed_offset: float | None = None  # NQ uses a hardcoded 15.75-pt offset


# Auto-detect table from the Pine script, GC row. Retained for reference only
# -- this handoff's frozen config uses NQ_PARAMS exclusively.
GC_PARAMS = InstrumentParams(sigma_mult=1.15, offset_pct=0.02, ib_minutes=30)
NQ_PARAMS = InstrumentParams(sigma_mult=1.25, offset_pct=0.07, ib_minutes=60, fixed_offset=15.75)


def generate_levels(
    ohlcv_1m: pd.DataFrame,
    vol_close: pd.Series,
    params: InstrumentParams = NQ_PARAMS,
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

        vix_close = prior_session_close(vol_close, session_date)
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
