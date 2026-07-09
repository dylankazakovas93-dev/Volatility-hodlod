"""Independent synthetic helpers for OG_OPERATIONAL_100R rule tests.

Zero calls to the existing src/ engine, runner, or rolling-PF code.
All functions are deterministically derived from the locked master-plan rules.
"""

from __future__ import annotations

import datetime
import math

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants (from canonical_config.json / master plan)
# ---------------------------------------------------------------------------
ET = "America/New_York"
SL_CAP = 200.0
BE_BARS = 45
ROLLING_WINDOW = 100
SHUTDOWN_THRESHOLD = 1.10
REENTRY_THRESHOLD = 1.10

# Entry blackout minutes-since-midnight ET (10:00-15:00)
ENTRY_BLOCKED_START = 600  # 10:00
ENTRY_BLOCKED_END = 900  # 15:00

# Prop hard blackout minutes-since-midnight ET (16:00-19:00)
PROP_HARD_BLACKOUT_START = 960  # 16:00
PROP_HARD_BLACKOUT_END = 1140  # 19:00


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def et_minute(ts: pd.Timestamp) -> int:
    """Minutes since midnight Eastern for a timestamp."""
    et = ts.tz_convert(ET) if ts.tz else ts.tz_localize(ET)
    return et.hour * 60 + et.minute


def entry_allowed(ts: pd.Timestamp) -> bool:
    """True if entry is not blocked by the 10:00-15:00 ET blackout."""
    m = et_minute(ts)
    return not (ENTRY_BLOCKED_START <= m < ENTRY_BLOCKED_END)


def in_prop_hard_blackout(ts: pd.Timestamp) -> bool:
    """True if ts falls within 16:00-19:00 ET (inclusive start, exclusive end)."""
    m = et_minute(ts)
    return PROP_HARD_BLACKOUT_START <= m < PROP_HARD_BLACKOUT_END


def session_cutoff(touched_at: pd.Timestamp) -> pd.Timestamp | None:
    """Reproduce frozen session_cutoff() logic (strict_engine.py:53-63)."""
    et = touched_at.tz_convert(ET)
    d = et.strftime("%Y-%m-%d")
    co = pd.Timestamp(f"{d} 15:00", tz=ET)
    re = pd.Timestamp(f"{d} 19:00", tz=ET)
    if et < co:
        return co.tz_convert(touched_at.tz)
    if et >= re:
        nxt = et.normalize() + pd.Timedelta(days=1)
        return pd.Timestamp(f"{nxt.date()} 15:00", tz=ET).tz_convert(touched_at.tz)
    return None


def make_timestamp(year, month, day, hour, minute, tz=ET):
    """Create a timezone-aware timestamp."""
    return pd.Timestamp(f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}", tz=tz)


# ---------------------------------------------------------------------------
# Synthetic bar construction
# ---------------------------------------------------------------------------

def make_bars(
    timestamps: list[pd.Timestamp],
    opens: list[float],
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[int] | None = None,
) -> pd.DataFrame:
    """Create a deterministic synthetic 1-minute bar DataFrame.

    All columns are float (or int for volume). Index is the timestamp list.
    """
    vols = volumes if volumes is not None else [100] * len(timestamps)
    df = pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols,
        },
        index=pd.DatetimeIndex(timestamps, name="timestamp"),
    )
    df.index = df.index.sort_values()
    return df


# ---------------------------------------------------------------------------
# Touch detection (independent, mirrors master-plan §5.2)
# ---------------------------------------------------------------------------

def first_touch(bars: pd.DataFrame, level: float) -> pd.Timestamp | None:
    """First bar where level is inside the bar's range OR close crosses
    relative to prior close. Independent of frozen src/strict_engine.py."""
    # Working on numpy arrays avoids pandas chaining edge cases
    high = bars["high"].to_numpy()
    low = bars["low"].to_numpy()
    close = bars["close"].to_numpy()
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]  # first bar: no prior close

    inside = (high >= level) & (low <= level)
    cross_up = (close >= level) & (prev_close < level)
    cross_down = (close <= level) & (prev_close > level)
    touched = inside | cross_up | cross_down

    hits = bars.index[touched]
    return hits[0] if len(hits) else None


def touch_is_clean(bar_row: pd.Series, level: float) -> bool:
    """True if level is within the bar's high-low range."""
    return bool(bar_row["low"] <= level <= bar_row["high"])


# ---------------------------------------------------------------------------
# Stop and target (master-plan §5.7, §5.8)
# ---------------------------------------------------------------------------

def stop_distance(hourly_range: float) -> float:
    """Capped stop distance: min(1.5 * hourly_range, 200)."""
    return min(1.5 * hourly_range, SL_CAP)


def orig_stop_long(entry_fill: float, stop_dist: float) -> float:
    return entry_fill - stop_dist


def orig_stop_short(entry_fill: float, stop_dist: float) -> float:
    return entry_fill + stop_dist


def target_long(entry_fill: float, stop_dist: float) -> float:
    return entry_fill + stop_dist


def target_short(entry_fill: float, stop_dist: float) -> float:
    return entry_fill - stop_dist


# ---------------------------------------------------------------------------
# BE45 state machine (master-plan §5.9, §5.10, §5.11)
# ---------------------------------------------------------------------------

def simulate_be45(
    bars: pd.DataFrame,
    touch_bar_idx: int,
    entry_fill: float,
    sign: float,
    stop_dist: float,
    be_bars: int = BE_BARS,
) -> tuple[float, str, pd.Timestamp]:
    """Simulate the OG_OPERATIONAL_100R state machine from the touch bar.

    Parameters
    ----------
    bars : DataFrame with o,h,l,c columns
    touch_bar_idx : integer index into bars of the touch bar
    entry_fill : entry price
    sign : 1.0 for long, -1.0 for short
    stop_dist : stop distance (capped)
    be_bars : number of bars before BE check (45)

    Returns
    -------
    (pnl_points, exit_type, exit_timestamp)
    exit_type in {"SL", "TP", "BE", "cutoff"}
    """
    cap = stop_dist
    orig_stop = entry_fill - sign * cap
    target = entry_fill + sign * cap

    hi = bars["high"].to_numpy()
    lo = bars["low"].to_numpy()
    op = bars["open"].to_numpy()
    cl = bars["close"].to_numpy()
    idx = bars.index

    touch_idx = touch_bar_idx
    h0 = float(hi[touch_idx])
    l0 = float(lo[touch_idx])

    # --- Touch bar: stop-only (master-plan §5.9) ---
    hit_stop = (l0 <= orig_stop) if sign > 0 else (h0 >= orig_stop)
    if hit_stop:
        return sign * (orig_stop - entry_fill), "SL", idx[touch_idx]

    # --- Post-touch bars: rest[0] ... rest[N] (master-plan §5.10, §5.11) ---
    # rest[0] is the first bar after the touch bar
    # skip the touch bar
    start = touch_idx + 1
    if start >= len(bars):
        return sign * (float(cl[touch_idx]) - entry_fill), "cutoff", idx[touch_idx]

    armed = False
    checked = False
    for i in range(start, len(hi)):
        bar_i = i - start  # zero-based index in "rest" sequence
        h = float(hi[i])
        l = float(lo[i])

        # Determine active stop
        if bar_i < be_bars:
            stop = orig_stop
        else:
            if not checked:
                checked = True
                o = float(op[i])
                # BE eligibility check using this bar's open (§5.10)
                armed = (o >= entry_fill) if sign > 0 else (o <= entry_fill)
            stop = entry_fill if armed else orig_stop

        # Check stop before target (§5.11)
        if sign > 0:
            if l <= stop:
                exit_type = "BE" if (bar_i >= be_bars and armed) else "SL"
                return sign * (stop - entry_fill), exit_type, idx[i]
            if h >= target:
                return cap, "TP", idx[i]
        else:
            if h >= stop:
                exit_type = "BE" if (bar_i >= be_bars and armed) else "SL"
                return sign * (stop - entry_fill), exit_type, idx[i]
            if l <= target:
                return cap, "TP", idx[i]

    # Cutoff: no stop, BE, or target hit before bars end
    return sign * (float(cl[-1]) - entry_fill), "cutoff", idx[-1]


# ---------------------------------------------------------------------------
# Rolling PF gate (master-plan §6)
# ---------------------------------------------------------------------------

def profit_factor(pnl: np.ndarray | list[float]) -> float:
    """PF = gains / losses if losses > 0 else inf. Mirrors frozen convention."""
    pnl = np.asarray(pnl, dtype=float)
    gains = float(pnl[pnl > 0].sum())
    losses = float(-pnl[pnl < 0].sum())
    return gains / losses if losses > 0 else float("inf")


def simulate_rolling_pf(
    pnl: np.ndarray | list[float],
    window: int = ROLLING_WINDOW,
    threshold: float = SHUTDOWN_THRESHOLD,
    reentry_threshold: float | None = None,
) -> np.ndarray:
    """Causal rolling PF state machine.

    Returns flat_mask: True where the strategy is OFF (flat).

    Reproduces the frozen rolling_pf_killswitch logic identically:
    - Start state: ON (flat=False)
    - First `window` rows: stay in initial ON state
    - For i >= window: PF over rows [i-window, i)
    - Symmetric re-entry when reentry_threshold == threshold
    """
    pnl = np.asarray(pnl, dtype=float)
    n = len(pnl)
    flat = np.zeros(n, dtype=bool)
    reentry_thr = reentry_threshold if reentry_threshold is not None else threshold

    state_flat = False  # start ON
    for i in range(n):
        if i >= window:
            trailing = pnl[i - window:i]
            gains = trailing[trailing > 0].sum()
            losses = -trailing[trailing < 0].sum()
            pf = gains / losses if losses > 0 else float("inf")
            if state_flat:
                if pf >= reentry_thr:
                    state_flat = False
            else:
                if pf < threshold:
                    state_flat = True
        flat[i] = state_flat
    return flat
