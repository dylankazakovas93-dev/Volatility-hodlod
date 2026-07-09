"""Independent synthetic helpers for OG_OPERATIONAL_100R rule tests.

Zero calls to the existing src/ engine, runner, or rolling-PF code.
All functions are deterministically derived from the locked master-plan rules.
"""

from __future__ import annotations

import datetime
import math
from collections import defaultdict

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
ENTRY_BLOCKED_START = 660  # 11:00
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


def session_date_frozen(ts: pd.Timestamp) -> str:
    """Session date per frozen logic: if hour >= 19 ET, use next day."""
    et = ts.tz_convert(ET)
    d = et.date()
    if et.hour >= 19:
        d = d + datetime.timedelta(days=1)
    return d.isoformat()


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
    high = bars["high"].to_numpy()
    low = bars["low"].to_numpy()
    close = bars["close"].to_numpy()
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]

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

    hit_stop = (l0 <= orig_stop) if sign > 0 else (h0 >= orig_stop)
    if hit_stop:
        return sign * (orig_stop - entry_fill), "SL", idx[touch_idx]

    start = touch_idx + 1
    if start >= len(bars):
        return sign * (float(cl[touch_idx]) - entry_fill), "cutoff", idx[touch_idx]

    armed = False
    checked = False
    for i in range(start, len(hi)):
        bar_i = i - start
        h = float(hi[i])
        l = float(lo[i])

        if bar_i < be_bars:
            stop = orig_stop
        else:
            if not checked:
                checked = True
                o = float(op[i])
                armed = (o >= entry_fill) if sign > 0 else (o <= entry_fill)
            stop = entry_fill if armed else orig_stop

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

    state_flat = False
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


# ---------------------------------------------------------------------------
# VXN / data loading (independent of src.data_loader)
# ---------------------------------------------------------------------------

def load_vxn_close(path: str) -> pd.Series:
    """Load VXN daily close from CSV, indexed by date. Mirrors frozen
    data_loader.load_gvz_daily. Expects columns: date, close."""
    df = pd.read_csv(path, parse_dates=["date"])
    return df.set_index("date")["close"].sort_index()


def prior_vxn_close(vxn_series: pd.Series, session_date_et: pd.Timestamp) -> float | None:
    """Most recent VXN close strictly before session_date_et.
    Reproduces frozen data_loader.prior_session_close()."""
    target = session_date_et.normalize().tz_localize(None)
    vxn_local = vxn_series.copy()
    vxn_local.index = vxn_local.index.tz_localize(None) if vxn_local.index.tz is None else vxn_local.index
    prior = vxn_local[vxn_local.index < target]
    if prior.empty:
        return None
    return float(prior.iloc[-1])


# ---------------------------------------------------------------------------
# Level generation (independent of src.level_generation)
# ---------------------------------------------------------------------------

def generate_levels(
    bars: pd.DataFrame,
    vxn_series: pd.Series,
    rth_start: str = "09:30",
    rth_end: str = "16:00",
    sigma_mult: float = 1.25,
    ib_minutes: int = 60,
    fixed_offset: float = 15.75,
    annual_trading_days: float = 252.0,
    line_days: int = 20,
) -> pd.DataFrame:
    """Independent per-session level generation reproducing the frozen
    OG_OPERATIONAL_100R level formula exactly.

    Parameters
    ----------
    bars : DataFrame with timestamp index (America/New_York), OHLCV columns
    vxn_series : Series with date index, close values
    rth_start, rth_end : RTH window boundaries ET
    sigma_mult : 1.25 for OG_OPERATIONAL_100R
    ib_minutes : 60-minute IB
    fixed_offset : 15.75 NQ offset
    annual_trading_days : 252
    line_days : 20-session level lifetime

    Returns
    -------
    DataFrame with one row per RTH session (where IB completed and VXN was
    available), containing cash_open, prior_vxn, sigma_day, ib_high/low/range,
    imp_up/dn, ib_ext_up/dn, upper_level, lower_level, created_at.
    """
    sessions = bars.between_time(rth_start, rth_end)
    rows = []

    for session_date, day_bars in sessions.groupby(sessions.index.date):
        if day_bars.empty:
            continue

        sd = pd.Timestamp(session_date, tz=bars.index.tz)
        cash_open = float(day_bars["open"].iloc[0])

        prior_vxn = prior_vxn_close(vxn_series, sd)
        if prior_vxn is None:
            continue

        sigma_day = cash_open * (prior_vxn / 100.0) / math.sqrt(annual_trading_days)
        imp_up = cash_open + sigma_mult * sigma_day
        imp_dn = cash_open - sigma_mult * sigma_day

        ib_cutoff = day_bars.index[0] + pd.Timedelta(minutes=ib_minutes)
        ib_bars = day_bars[day_bars.index <= ib_cutoff]
        if ib_bars.empty:
            continue
        ib_high = float(ib_bars["high"].max())
        ib_low = float(ib_bars["low"].min())
        ib_range = ib_high - ib_low
        ib_ext_up = ib_high + ib_range
        ib_ext_dn = ib_low - ib_range

        upper_level = (ib_ext_up + imp_up) / 2 - fixed_offset
        lower_level = (ib_ext_dn + imp_dn) / 2 + fixed_offset

        live_bars = day_bars[day_bars.index >= ib_cutoff]
        if live_bars.empty:
            continue
        created_at = live_bars.index[0]

        rows.append({
            "session_date": session_date,
            "created_at": created_at,
            "cash_open": cash_open,
            "prior_vxn_close": prior_vxn,
            "sigma_day": sigma_day,
            "ib_high": ib_high,
            "ib_low": ib_low,
            "ib_range": ib_range,
            "imp_up": imp_up,
            "imp_dn": imp_dn,
            "ib_ext_up": ib_ext_up,
            "ib_ext_dn": ib_ext_dn,
            "upper_level": upper_level,
            "lower_level": lower_level,
        })

    return pd.DataFrame(rows)


def add_level_expiry(levels: pd.DataFrame, line_days: int = 20, bars_end: pd.Timestamp = None) -> pd.DataFrame:
    """Add expiry_at column: expiry = levels[i + line_days].created_at, or
    bars_end if within line_days of the end."""
    n = len(levels)
    if bars_end is None:
        bars_end = pd.Timestamp.now(tz=ET)
    expiries = []
    for i in range(n):
        if i + line_days < n:
            expiries.append(levels.iloc[i + line_days]["created_at"])
        else:
            expiries.append(bars_end)
    levels = levels.copy()
    levels["expiry_at"] = expiries
    return levels


# ---------------------------------------------------------------------------
# Hourly anchor / completed-range helpers
# ---------------------------------------------------------------------------

def bar_ranges(bars: pd.DataFrame) -> pd.Series:
    """Resample bars into 60-min buckets and return the range (high-low)."""
    r = bars.resample("60min", label="left", closed="left").agg(
        {"high": "max", "low": "min"}
    ).dropna()
    return r["high"] - r["low"]


def prev_completed_range(ranges: pd.Series, ts: pd.Timestamp) -> float | None:
    """Previous completed hourly bucket's range."""
    prev = ts.floor("60min") - pd.Timedelta(minutes=60)
    v = ranges.get(prev)
    if v is not None and not pd.isna(v) and v > 0:
        return float(v)
    return None


# ---------------------------------------------------------------------------
# Physical touch extraction (independent, mirrors frozen strict_engine)
# ---------------------------------------------------------------------------

def physical_touches_independent(
    bars: pd.DataFrame,
    levels: pd.DataFrame,
    line_days: int = 20,
    creation_bar_exclude: bool = True,
    expiry_exclude: bool = True,
) -> list[dict]:
    """Mirrors frozen physical_touches() exactly. One row per level-side."""
    n = len(levels)
    events = []
    for i, lv in levels.iterrows():
        expiry = lv["expiry_at"]
        window = bars.loc[lv["created_at"]: expiry]
        if creation_bar_exclude:
            window = window[window.index > lv["created_at"]]
        if expiry_exclude:
            window = window[window.index < expiry]
        for side, col in (("upper", lv["upper_level"]), ("lower", lv["lower_level"])):
            lvl_val = float(col)
            ft = first_touch(window, lvl_val) if not window.empty else None
            events.append({
                "level_id": f"{i}_{side}",
                "level_idx": i,
                "session_date": lv.get("session_date", session_date_frozen(lv["created_at"])),
                "created_at": lv["created_at"],
                "expiry_at": expiry,
                "side": side,
                "level": lvl_val,
                "touched_at": ft,
            })
    return events


# ---------------------------------------------------------------------------
# Independent simulate_from_touch (mirrors frozen strict_engine)
# ---------------------------------------------------------------------------

def simulate_from_touch_independent(
    bars: pd.DataFrame,
    touched_at: pd.Timestamp,
    cutoff: pd.Timestamp,
    entry_fill: float,
    sign: float,
    cap: float,
    be_bars: int = BE_BARS,
) -> tuple[float, str, pd.Timestamp]:
    """Mirrors frozen simulate_from_touch exactly. Returns (pnl, exit_type, exit_ts)."""
    touch_row = bars.loc[touched_at]
    orig_stop = entry_fill - sign * cap
    h0, l0 = float(touch_row["high"]), float(touch_row["low"])
    hit_stop = (l0 <= orig_stop) if sign > 0 else (h0 >= orig_stop)
    if hit_stop:
        return sign * (orig_stop - entry_fill), "SL", touched_at

    rest = bars.loc[touched_at: cutoff].iloc[1:]
    if rest.empty:
        return sign * (float(touch_row["close"]) - entry_fill), "cutoff", touched_at

    target = entry_fill + sign * cap
    hi, lo, op, cl = (rest["high"].values, rest["low"].values, rest["open"].values, rest["close"].values)
    idx = rest.index
    armed = False
    checked = False
    for i in range(len(hi)):
        h, l = float(hi[i]), float(lo[i])
        if i < be_bars:
            stop = orig_stop
        else:
            if not checked:
                checked = True
                o = float(op[i])
                armed = (o >= entry_fill) if sign > 0 else (o <= entry_fill)
            stop = entry_fill if armed else orig_stop
        if sign > 0:
            if l <= stop:
                return sign * (stop - entry_fill), ("BE" if (i >= be_bars and armed) else "SL"), idx[i]
            if h >= target:
                return cap, "TP", idx[i]
        else:
            if h >= stop:
                return sign * (stop - entry_fill), ("BE" if (i >= be_bars and armed) else "SL"), idx[i]
            if l <= target:
                return cap, "TP", idx[i]
    return sign * (float(cl[-1]) - entry_fill), "cutoff", idx[-1] if len(idx) else touched_at


# ---------------------------------------------------------------------------
# Independent run_strict engine (mirrors frozen strict_engine.run_strict)
# ---------------------------------------------------------------------------

def run_strict_independent(
    bars: pd.DataFrame,
    events: list[dict],
    tie_order: str = "age",
) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """Chronological, single-global-position, time-aware-SAL state machine.

    Mirrors frozen strict_engine.run_strict exactly. Returns (summary, ex_df, rows_df).
    """
    ranges = bar_ranges(bars)

    touched = [e for e in events if e["touched_at"] is not None]
    total_physical_touches = len(touched)

    for e in touched:
        pos = bars.index.get_indexer([e["touched_at"]])[0]
        e["prior_close"] = float(bars["close"].iloc[pos - 1]) if pos > 0 else float(bars["close"].iloc[pos])
        e["dist_prior_close"] = abs(e["level"] - e["prior_close"])

    groups = defaultdict(list)
    for e in touched:
        groups[e["touched_at"]].append(e)

    rows, executed = [], []
    skip_counts = defaultdict(int)
    simultaneous_groups = 0
    gap_count = 0
    gap_pnl_delta = 0.0

    pos_exit_time = None
    sal_session = None
    sal_armed_at = None

    def record_skip(ev, reason, pos_state, sal_state):
        skip_counts[reason] += 1
        rows.append({
            "level_id": ev["level_id"], "session_date": ev["session_date"],
            "created_at": ev["created_at"], "expiry_at": ev["expiry_at"],
            "physical_touch": ev["touched_at"], "side": ev["side"],
            "eligibility": "skipped", "skip_reason": reason,
            "position_state": pos_state, "sal_state": sal_state,
            "entry_time": None, "exit_time": None, "entry_price": None,
            "exit_price": None, "anchor": None, "cap": None,
            "exit_reason": None, "pnl": None,
        })

    for ts in sorted(groups.keys()):
        group = groups[ts]

        anchor = prev_completed_range(ranges, ts)
        if anchor is None:
            for e in group:
                record_skip(e, "no_anchor", "n/a", "n/a")
            continue

        if not entry_allowed(ts):
            for e in group:
                record_skip(e, "blocked_time", "n/a", "n/a")
            continue

        cutoff = session_cutoff(ts)
        if cutoff is None:
            for e in group:
                record_skip(e, "no_cutoff", "n/a", "n/a")
            continue

        sess = session_date_frozen(ts)
        if sess != sal_session:
            sal_session = sess
            sal_armed_at = None

        sal_state_before = "active" if sal_armed_at is not None else "inactive"

        if sal_armed_at is not None and ts >= sal_armed_at:
            for e in group:
                record_skip(e, "SAL", "n/a", sal_state_before)
            continue

        pos_state = "open" if (pos_exit_time is not None and ts <= pos_exit_time) else "flat"
        if pos_exit_time is not None and ts < pos_exit_time:
            for e in group:
                record_skip(e, "position_open", pos_state, sal_state_before)
            continue
        if pos_exit_time is not None and ts == pos_exit_time:
            for e in group:
                record_skip(e, "same_bar_reentry", "reopen_blocked", sal_state_before)
            continue

        if len(group) > 1:
            simultaneous_groups += 1
            if tie_order == "age":
                ordered = sorted(group, key=lambda e: (e["created_at"], e["side"]))
            elif tie_order == "nearest":
                ordered = sorted(group, key=lambda e: e["dist_prior_close"])
            elif tie_order == "farthest":
                ordered = sorted(group, key=lambda e: -e["dist_prior_close"])
            else:
                raise ValueError(f"unknown tie_order {tie_order}")
            chosen, losers = ordered[0], ordered[1:]
            for e in losers:
                record_skip(e, "simultaneous_collision", pos_state, sal_state_before)
        else:
            chosen = group[0]

        sign = -1.0 if chosen["side"] == "upper" else 1.0
        cap = min(1.5 * anchor, SL_CAP)
        clean = touch_is_clean(bars.loc[ts], chosen["level"])
        fill = chosen["level"] if clean else float(bars.loc[ts, "close"])

        if not clean:
            gap_count += 1
            p_level, _, _ = simulate_from_touch_independent(bars, ts, cutoff, chosen["level"], sign, cap)
            p_adj, ex_adj, exit_ts_adj = simulate_from_touch_independent(bars, ts, cutoff, fill, sign, cap)
            gap_pnl_delta += (p_adj - p_level)
            pnl, ex, exit_ts = p_adj, ex_adj, exit_ts_adj
        else:
            pnl, ex, exit_ts = simulate_from_touch_independent(bars, ts, cutoff, fill, sign, cap)

        year = pd.Timestamp(sess).year
        exit_price = fill + sign * pnl
        executed.append({
            "level_id": chosen["level_id"], "session_date": sess, "year": year,
            "side": chosen["side"], "entry_time": ts, "exit_time": exit_ts,
            "entry_price": fill, "exit_price": exit_price, "level": chosen["level"],
            "anchor": anchor, "cap": cap,
            "exit_reason": ex, "pnl": pnl, "gap_through": not clean,
        })
        rows.append({
            "level_id": chosen["level_id"], "session_date": sess,
            "created_at": chosen["created_at"], "expiry_at": chosen["expiry_at"],
            "physical_touch": ts, "side": chosen["side"],
            "eligibility": "executed", "skip_reason": None,
            "position_state": pos_state, "sal_state": sal_state_before,
            "entry_time": ts, "exit_time": exit_ts, "entry_price": fill,
            "exit_price": exit_price,
            "anchor": anchor, "cap": cap, "exit_reason": ex, "pnl": pnl,
        })

        pos_exit_time = exit_ts
        if pnl < -0.1 and ex != "BE":
            sal_armed_at = exit_ts

    ex_df = pd.DataFrame(executed)
    summary = {
        "total_physical_touches": total_physical_touches,
        "executed": len(ex_df),
        "skipped_no_anchor": skip_counts.get("no_anchor", 0),
        "skipped_blocked_time": skip_counts.get("blocked_time", 0),
        "skipped_no_cutoff": skip_counts.get("no_cutoff", 0),
        "skipped_SAL": skip_counts.get("SAL", 0),
        "skipped_position_open": skip_counts.get("position_open", 0),
        "skipped_same_bar_reentry": skip_counts.get("same_bar_reentry", 0),
        "skipped_simultaneous_collision": skip_counts.get("simultaneous_collision", 0),
        "simultaneous_groups": simultaneous_groups,
        "gap_through_count": gap_count,
        "gap_through_pnl_delta": round(gap_pnl_delta, 3),
    }
    if len(ex_df):
        exs = ex_df["exit_reason"].value_counts()
        pnl = ex_df["pnl"]
        summary.update({
            "TP": int(exs.get("TP", 0)), "SL": int(exs.get("SL", 0)),
            "BE": int(exs.get("BE", 0)), "cutoff": int(exs.get("cutoff", 0)),
            "net_pts": round(float(pnl.sum()), 2),
            "PF": round(profit_factor(pnl), 4),
            "win_rate": round(float((pnl > 0).mean()), 4),
            "twr": round(int(exs.get("TP", 0)) / max(1, int(exs.get("TP", 0)) + int(exs.get("SL", 0))), 4),
            "avg_trade": round(float(pnl.mean()), 3),
            "max_drawdown": round(_max_drawdown(pnl), 2),
            "max_loss_streak": _max_loss_streak(ex_df["exit_reason"].tolist(), pnl.tolist()),
        })
        cost_adjusted = {}
        for cost in (0.0, 0.5, 1.0, 2.0):
            pnl_c = pnl - cost
            cost_adjusted[f"cost_{cost}"] = {
                "net_pts": round(float(pnl_c.sum()), 2),
                "PF": round(profit_factor(pnl_c), 4),
                "max_drawdown": round(_max_drawdown(pnl_c), 2),
                "avg_trade": round(float(pnl_c.mean()), 3),
            }
        summary["cost_adjusted"] = cost_adjusted
        yearly = []
        for yr, s in ex_df.groupby("year"):
            yearly.append({
                "year": int(yr), "n": len(s), "net_pts": round(float(s["pnl"].sum()), 2),
                "PF": round(profit_factor(s["pnl"]), 4),
                "max_drawdown": round(_max_drawdown(s["pnl"]), 2),
                "avg_trade": round(float(s["pnl"].mean()), 3),
            })
        summary["yearly"] = yearly
        summary["negative_years"] = [y["year"] for y in yearly if y["net_pts"] < 0]
    else:
        summary["yearly"] = []
        summary["negative_years"] = []

    return summary, ex_df, pd.DataFrame(rows)


def _max_drawdown(pnl: pd.Series | np.ndarray) -> float:
    """Maximum peak-to-trough drawdown of cumulative PnL (negative)."""
    pnl = np.asarray(pnl, dtype=float)
    cum = np.cumsum(pnl)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    return float(dd.min())


def _max_loss_streak(exits: list[str], pnl: list[float]) -> int:
    """Longest consecutive non-TP sequence (SL, BE, cutoff) with negative PnL."""
    streak = 0
    best = 0
    for ex, p in zip(exits, pnl):
        if ex != "TP" and p < 0:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return best
