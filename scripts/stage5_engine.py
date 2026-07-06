"""Stage 5: configurable entry-window + configurable-cutoff replay engine,
built on top of the frozen F2 TP/SL + profit_lock_0.75R management +
hmm3_exclude_LOW_VOL regime gate (all unchanged from Stage 3/4).

Blocks (session-relative minutes since 18:00 ET session start):
    A: 18:00-00:00 ->    0- 360
    B: 00:00-02:00 ->  360- 480
    C: 02:00-03:00 ->  480- 540
    D: 03:00-05:00 ->  540- 660
    E: 05:00-06:00 ->  660- 720
    F: 06:00-08:00 ->  720- 840
    G: 08:00-09:00 ->  840- 900
    H: 09:00-09:30 ->  900- 930
    I: 09:30-11:00 ->  930-1020

Sessions (for broken-window tests):
    Asia:     A            (0-360)
    London:   C+D+E        (480-720)
    New York: H+I          (900-1020)
"""
from __future__ import annotations

import pandas as pd

from scripts.stage2_engine import session_start_ts, ET
import scripts.stage3_engine as s3

BLOCKS = {
    "A": (0, 360), "B": (360, 480), "C": (480, 540), "D": (540, 660),
    "E": (660, 720), "F": (720, 840), "G": (840, 900), "H": (900, 930),
    "I": (930, 1020),
}
BLOCK_ORDER = ["A", "B", "C", "D", "E", "F", "G", "H", "I"]

ASIA = {"A"}
LONDON = {"C", "D", "E"}
NEW_YORK = {"H", "I"}

CUTOFF_MINUTES = {"11:00": 1020, "12:00": 1080, "13:00": 1140, "14:00": 1200,
                  "15:00": 1260, "15:59": 1319}


def block_of(minutes_elapsed):
    for name, (lo, hi) in BLOCKS.items():
        if lo <= minutes_elapsed < hi:
            return name
    return None


def in_allowed_blocks(minutes_elapsed, allowed_blocks):
    b = block_of(minutes_elapsed)
    return b is not None and b in allowed_blocks


def in_minute_range(minutes_elapsed, lo, hi):
    return lo <= minutes_elapsed < hi


def contiguous_windows():
    """All contiguous combinations of the 9 blocks (36 windows)."""
    out = []
    n = len(BLOCK_ORDER)
    for length in range(1, n + 1):
        for start in range(0, n - length + 1):
            blocks = tuple(BLOCK_ORDER[start:start + length])
            out.append(blocks)
    return out


def session_cutoff_ts(session_date, cutoff_minutes):
    start = session_start_ts(session_date)
    return (start + pd.Timedelta(minutes=cutoff_minutes)).tz_convert("UTC")


def run_replay(bars, master_with_dist, allow_entry_fn, cutoff_minutes=1319):
    """allow_entry_fn(minutes_elapsed) -> bool. cutoff_minutes: session-
    relative minute of forced liquidation (default 1319 = 15:59 ET)."""
    from scripts.stage2_engine import DEV_YEARS, minutes_since_session_start

    df = master_with_dist.dropna(subset=["tp_dist_stage2", "sl_dist_stage2"]).sort_values("touched_at")
    executed = []
    skip_counts = {"blocked_reserved_year": 0, "blocked_window": 0, "blocked_regime": 0,
                   "blocked_at_or_after_cutoff": 0, "position_open": 0, "same_bar_reentry": 0}
    position_open_until = None

    for row in df.itertuples(index=False):
        ts = getattr(row, "touched_at")
        sess = getattr(row, "session_date")
        year = getattr(row, "year")

        if year not in DEV_YEARS:
            skip_counts["blocked_reserved_year"] += 1
            continue

        minutes_elapsed = minutes_since_session_start(ts, sess)

        if minutes_elapsed >= cutoff_minutes:
            skip_counts["blocked_at_or_after_cutoff"] += 1
            continue

        if not allow_entry_fn(minutes_elapsed):
            skip_counts["blocked_window"] += 1
            continue

        hmm3_state = getattr(row, "hmm3_state", None)
        if hmm3_state is None or (isinstance(hmm3_state, float) and pd.isna(hmm3_state)):
            skip_counts["blocked_regime"] += 1
            continue
        if hmm3_state == "LOW_VOL":
            skip_counts["blocked_regime"] += 1
            continue

        if position_open_until is not None and ts < position_open_until:
            skip_counts["position_open"] += 1
            continue
        if position_open_until is not None and ts == position_open_until:
            skip_counts["same_bar_reentry"] += 1
            continue

        side = getattr(row, "side")
        sign = 1.0 if side == "lower" else -1.0
        entry_price = getattr(row, "entry_price")
        cutoff_ts = session_cutoff_ts(sess, cutoff_minutes)
        tp_dist = getattr(row, "tp_dist_stage2")
        sl_dist = getattr(row, "sl_dist_stage2")

        pnl, reason, exit_ts, audit = s3.simulate_exact_r_be(
            bars, ts, cutoff_ts, entry_price, sign, tp_dist, sl_dist, trigger_r=0.75, lock_r=0.10)

        hold_minutes = int((exit_ts - ts) / pd.Timedelta(minutes=1))
        executed.append({
            "level_id": getattr(row, "level_id"), "session_date": sess, "year": year,
            "side": side, "entry_time": ts, "exit_time": exit_ts,
            "entry_price": entry_price, "tp_dist": tp_dist, "sl_dist": sl_dist,
            "pnl_pts": pnl, "r_multiple": pnl / sl_dist, "exit_reason": reason,
            "hold_minutes": hold_minutes,
        })
        position_open_until = exit_ts

    return pd.DataFrame(executed), skip_counts
