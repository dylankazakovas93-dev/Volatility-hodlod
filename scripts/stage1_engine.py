"""Stage 1 first-passage TP/SL replay engine -- shared by the simple-surface
and learned-formula runners.

Rules (frozen, section 12 of the Stage 1 spec):
  - one global position; a touch while a position is open is consumed and
    skipped (never retried);
  - TP/SL are computed once at entry from causal pre-entry information and
    never recalculated;
  - entry bar: only the stop is checked (conservative -- an entry-bar TP is
    never credited, since causal intrabar ordering cannot prove TP occurred
    after entry);
  - later bars: if only TP reached, exit TP; if only SL reached, exit SL;
    if both reached on the same bar, ordering is unknowable -> exit SL;
  - if neither resolves before the session's forced-liquidation bar
    (15:59 ET, or the stress-test cutoff), exit at that bar's close;
  - TP distance rounds UP to the next 0.25 tick, SL distance rounds DOWN to
    the prior 0.25 tick, both floored at a minimum 0.25 distance.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TICK = 0.25


def round_tp(distance):
    d = np.ceil(distance / TICK) * TICK
    return np.maximum(d, TICK)


def round_sl(distance):
    d = np.floor(distance / TICK) * TICK
    return np.maximum(d, TICK)


def first_passage_exit(bars, touch_ts, cutoff_ts, entry_price, sign, tp_dist, sl_dist):
    """sign=+1 long, -1 short. Returns (pnl_pts, exit_reason, exit_ts)."""
    touch_row = bars.loc[touch_ts]
    stop = entry_price - sign * sl_dist
    target = entry_price + sign * tp_dist

    entry_bar_hit_stop = (float(touch_row["low"]) <= stop) if sign > 0 else (float(touch_row["high"]) >= stop)
    if entry_bar_hit_stop:
        return sign * (stop - entry_price), "SL", touch_ts

    rest = bars.loc[touch_ts:cutoff_ts].iloc[1:]
    if rest.empty:
        return sign * (float(touch_row["close"]) - entry_price), "cutoff", touch_ts

    hi = rest["high"].to_numpy()
    lo = rest["low"].to_numpy()
    cl = rest["close"].to_numpy()
    idx = rest.index

    if sign > 0:
        hit_tp = hi >= target
        hit_sl = lo <= stop
    else:
        hit_tp = lo <= target
        hit_sl = hi >= stop

    both = hit_tp & hit_sl
    only_tp = hit_tp & ~hit_sl
    only_sl = hit_sl & ~hit_tp

    resolved = both | only_tp | only_sl
    resolved_idx = np.flatnonzero(resolved)
    if resolved_idx.size == 0:
        last = len(cl) - 1
        return sign * (float(cl[last]) - entry_price), "cutoff", idx[last]

    i = resolved_idx[0]
    if only_tp[i]:
        return tp_dist, "TP", idx[i]
    # both[i] or only_sl[i] -> same-bar ambiguity or pure SL both resolve to SL
    return sign * (stop - entry_price), "SL", idx[i]


def run_replay(bars, touches_df, tp_dist_col, sl_dist_col, cost_pts=1.0):
    """touches_df: chronologically-sortable frame with columns
    [touched_at, forced_liquidation_ts, side, entry_price, level_id,
     session_date, year, tp_dist_col, sl_dist_col]. One-position replay.
    """
    df = touches_df.sort_values("touched_at").reset_index(drop=True)
    executed = []
    position_open_until = None
    skipped_position_open = 0

    for row in df.itertuples(index=False):
        ts = getattr(row, "touched_at")
        if position_open_until is not None and ts <= position_open_until:
            skipped_position_open += 1
            continue

        side = getattr(row, "side")
        sign = 1.0 if side == "lower" else -1.0
        entry_price = getattr(row, "entry_price")
        cutoff_ts = getattr(row, "forced_liquidation_ts")
        tp_dist = getattr(row, tp_dist_col)
        sl_dist = getattr(row, sl_dist_col)
        if pd.isna(tp_dist) or pd.isna(sl_dist) or tp_dist <= 0 or sl_dist <= 0:
            continue

        pnl, reason, exit_ts = first_passage_exit(bars, ts, cutoff_ts, entry_price, sign, tp_dist, sl_dist)
        pnl_after_cost = pnl - cost_pts

        executed.append({
            "level_id": getattr(row, "level_id"),
            "session_date": getattr(row, "session_date"),
            "year": getattr(row, "year"),
            "side": side,
            "entry_time": ts, "exit_time": exit_ts,
            "entry_price": entry_price, "tp_dist": tp_dist, "sl_dist": sl_dist,
            "pnl_pts": pnl, "pnl_after_cost": pnl_after_cost,
            "r_multiple": pnl_after_cost / sl_dist,
            "exit_reason": reason,
        })
        position_open_until = exit_ts

    return pd.DataFrame(executed), skipped_position_open
