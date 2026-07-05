"""Stage 4: 5-minute session-anchored bars and session inventory shared by
the GARCH and HMM regime models.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.build_signal_paths import research_session_date
from scripts.build_session_anchored_rvol import session_start_ts

ET = "America/New_York"


def build_5min_bars(bars_1m):
    """Resample 1-min OHLCV to 5-min bars, each tagged with its research
    session date and minutes-since-session-start (18:00 ET)."""
    o = bars_1m["open"].resample("5min", label="left", closed="left").first()
    h = bars_1m["high"].resample("5min", label="left", closed="left").max()
    l = bars_1m["low"].resample("5min", label="left", closed="left").min()
    c = bars_1m["close"].resample("5min", label="left", closed="left").last()
    df = pd.DataFrame({"open": o, "high": h, "low": l, "close": c}).dropna()

    index_et = df.index.tz_convert(ET)
    sessions = []
    starts = []
    for ts in df.index:
        sess = research_session_date(ts)
        sessions.append(sess)
    df["session_date"] = sessions
    starts_map = {s: session_start_ts(s) for s in set(sessions)}
    df["session_start"] = [starts_map[s] for s in sessions]
    df["minutes_since_start"] = (
        (df.index.tz_convert(ET).tz_localize(None)
         - pd.DatetimeIndex([t.tz_localize(None) for t in df["session_start"]]))
        / pd.Timedelta(minutes=1)
    ).astype(int)
    df["log_return"] = np.log(df["close"]).diff()
    return df


def session_order(bars_5m):
    """Chronologically sorted list of distinct research session dates."""
    return sorted(bars_5m["session_date"].unique())


def trailing_sessions(all_sessions, current_session, max_sessions=120, min_sessions=20):
    """Up to `max_sessions` sessions strictly before `current_session`, or
    None if fewer than `min_sessions` are available."""
    pos = all_sessions.index(current_session) if current_session in all_sessions else \
        np.searchsorted(all_sessions, current_session)
    prior = all_sessions[max(0, pos - max_sessions):pos]
    if len(prior) < min_sessions:
        return None
    return prior
