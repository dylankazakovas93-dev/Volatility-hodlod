"""Stage 3: breakeven / scratch-management candidate simulations.

Every candidate here is a bar-by-bar simulation (not a pure first-passage
lookup, since management rules need to observe intrabar progress). All
share:
  - touch bar: only the ORIGINAL stop is checked (no TP, no management) --
    identical to the frozen engine's existing touch-bar convention;
  - original TP and SL are fixed at entry and never recalculated;
  - a trigger detected using bar T's data becomes active starting at bar
    T+1, NEVER bar T itself (the one deliberate, documented exception is
    stage3_engine.simulate_be45, which reproduces the historical BE45
    same-bar activation verbatim -- see
    docs/STAGE3_BE45_HISTORICAL_SEMANTICS.md);
  - on the trigger bar itself, only the original TP/SL are checked;
  - if both original TP and SL are touched on one bar with unknowable
    ordering, resolve to SL;
  - a management rule may move the stop at most once (except
    scratch-on-recovery, which arms a *separate* recovery-to-entry exit
    condition, not a stop move).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _path_arrays(bars, touch_ts, cutoff_ts):
    rest = bars.loc[touch_ts:cutoff_ts].iloc[1:]
    return rest


def _touch_bar_stop_check(bars, touch_ts, entry, sign, sl_dist):
    touch_row = bars.loc[touch_ts]
    stop = entry - sign * sl_dist
    hit = (float(touch_row["low"]) <= stop) if sign > 0 else (float(touch_row["high"]) >= stop)
    if hit:
        return sign * (stop - entry), "SL", touch_ts
    return None


def simulate_no_management(bars, touch_ts, cutoff_ts, entry, sign, tp_dist, sl_dist):
    """Baseline: original TP/SL only, no BE/scratch."""
    tb = _touch_bar_stop_check(bars, touch_ts, entry, sign, sl_dist)
    if tb is not None:
        return (*tb, {})
    rest = _path_arrays(bars, touch_ts, cutoff_ts)
    if rest.empty:
        return sign * (float(bars.loc[touch_ts, "close"]) - entry), "cutoff", touch_ts, {}

    stop = entry - sign * sl_dist
    target = entry + sign * tp_dist
    hi, lo, cl = rest["high"].to_numpy(), rest["low"].to_numpy(), rest["close"].to_numpy()
    idx = rest.index
    for i in range(len(hi)):
        h, l = float(hi[i]), float(lo[i])
        if sign > 0:
            if l <= stop:
                return sign * (stop - entry), "SL", idx[i], {}
            if h >= target:
                return tp_dist, "TP", idx[i], {}
        else:
            if h >= stop:
                return sign * (stop - entry), "SL", idx[i], {}
            if l <= target:
                return tp_dist, "TP", idx[i], {}
    return sign * (float(cl[-1]) - entry), "cutoff", idx[-1], {}


def simulate_be45(bars, touch_ts, cutoff_ts, entry, sign, tp_dist, sl_dist, be_bar=45):
    """Exact historical BE45 semantics (same-bar activation) -- see
    docs/STAGE3_BE45_HISTORICAL_SEMANTICS.md."""
    tb = _touch_bar_stop_check(bars, touch_ts, entry, sign, sl_dist)
    if tb is not None:
        return (*tb, {})
    rest = _path_arrays(bars, touch_ts, cutoff_ts)
    if rest.empty:
        return sign * (float(bars.loc[touch_ts, "close"]) - entry), "cutoff", touch_ts, {}

    orig_stop = entry - sign * sl_dist
    target = entry + sign * tp_dist
    hi, lo, op, cl = (rest["high"].to_numpy(), rest["low"].to_numpy(),
                      rest["open"].to_numpy(), rest["close"].to_numpy())
    idx = rest.index
    armed = checked = False
    audit = {}
    for i in range(len(hi)):
        h, l = float(hi[i]), float(lo[i])
        if i < be_bar:
            stop = orig_stop
        else:
            if not checked:
                checked = True
                o = float(op[i])
                armed = (o >= entry) if sign > 0 else (o <= entry)
                audit["be45_checkpoint_ts"] = idx[i]
                audit["be45_armed"] = armed
            stop = entry if armed else orig_stop
        if sign > 0:
            if l <= stop:
                return sign * (stop - entry), ("BE" if (i >= be_bar and armed) else "SL"), idx[i], audit
            if h >= target:
                return tp_dist, "TP", idx[i], audit
        else:
            if h >= stop:
                return sign * (stop - entry), ("BE" if (i >= be_bar and armed) else "SL"), idx[i], audit
            if l <= target:
                return tp_dist, "TP", idx[i], audit
    return sign * (float(cl[-1]) - entry), "cutoff", idx[-1], audit


def simulate_exact_r_be(bars, touch_ts, cutoff_ts, entry, sign, tp_dist, sl_dist, trigger_r,
                        lock_r=None):
    """R-triggered exact breakeven (lock_r=None) or small-profit-lock
    (lock_r=0.10 -- moves stop to entry + lock_r*R in the profit direction,
    instead of exactly to entry). Next-bar activation."""
    tb = _touch_bar_stop_check(bars, touch_ts, entry, sign, sl_dist)
    if tb is not None:
        return (*tb, {})
    rest = _path_arrays(bars, touch_ts, cutoff_ts)
    if rest.empty:
        return sign * (float(bars.loc[touch_ts, "close"]) - entry), "cutoff", touch_ts, {}

    orig_stop = entry - sign * sl_dist
    target = entry + sign * tp_dist
    new_stop_price = entry if lock_r is None else entry + sign * lock_r * sl_dist
    exit_label = "BE" if lock_r is None else "LOCK"

    hi, lo = rest["high"].to_numpy(), rest["low"].to_numpy()
    cl = rest["close"].to_numpy()
    idx = rest.index

    running_max_fav = -np.inf
    triggered_active = False   # becomes True starting the bar AFTER the trigger bar
    trigger_pending_next_bar = False
    audit = {}

    for i in range(len(hi)):
        h, l = float(hi[i]), float(lo[i])
        if trigger_pending_next_bar:
            triggered_active = True
            trigger_pending_next_bar = False
            audit["trigger_activated_ts"] = idx[i]

        stop = new_stop_price if triggered_active else orig_stop

        if sign > 0:
            if l <= stop:
                reason = exit_label if triggered_active else "SL"
                return sign * (stop - entry), reason, idx[i], audit
            if h >= target:
                return tp_dist, "TP", idx[i], audit
            fav = h - entry
        else:
            if h >= stop:
                reason = exit_label if triggered_active else "SL"
                return sign * (stop - entry), reason, idx[i], audit
            if l <= target:
                return tp_dist, "TP", idx[i], audit
            fav = entry - l

        running_max_fav = max(running_max_fav, fav)
        if not triggered_active and not trigger_pending_next_bar:
            if running_max_fav >= trigger_r * sl_dist:
                trigger_pending_next_bar = True
                audit["trigger_bar_ts"] = idx[i]

    return sign * (float(cl[-1]) - entry), "cutoff", idx[-1], audit


def simulate_tp_progress_be(bars, touch_ts, cutoff_ts, entry, sign, tp_dist, sl_dist, trigger_frac):
    """BE triggered by TP-progress fraction instead of R-multiple."""
    tb = _touch_bar_stop_check(bars, touch_ts, entry, sign, sl_dist)
    if tb is not None:
        return (*tb, {})
    rest = _path_arrays(bars, touch_ts, cutoff_ts)
    if rest.empty:
        return sign * (float(bars.loc[touch_ts, "close"]) - entry), "cutoff", touch_ts, {}

    orig_stop = entry - sign * sl_dist
    target = entry + sign * tp_dist
    hi, lo, cl = rest["high"].to_numpy(), rest["low"].to_numpy(), rest["close"].to_numpy()
    idx = rest.index

    running_max_fav = -np.inf
    triggered_active = trigger_pending = False
    audit = {}

    for i in range(len(hi)):
        h, l = float(hi[i]), float(lo[i])
        if trigger_pending:
            triggered_active = True
            trigger_pending = False
            audit["trigger_activated_ts"] = idx[i]

        stop = entry if triggered_active else orig_stop

        if sign > 0:
            if l <= stop:
                return sign * (stop - entry), ("BE" if triggered_active else "SL"), idx[i], audit
            if h >= target:
                return tp_dist, "TP", idx[i], audit
            fav = h - entry
        else:
            if h >= stop:
                return sign * (stop - entry), ("BE" if triggered_active else "SL"), idx[i], audit
            if l <= target:
                return tp_dist, "TP", idx[i], audit
            fav = entry - l

        running_max_fav = max(running_max_fav, fav)
        if not triggered_active and not trigger_pending:
            if running_max_fav >= trigger_frac * tp_dist:
                trigger_pending = True
                audit["trigger_bar_ts"] = idx[i]

    return sign * (float(cl[-1]) - entry), "cutoff", idx[-1], audit


def simulate_time_delayed_be(bars, touch_ts, cutoff_ts, entry, sign, tp_dist, sl_dist,
                              minutes, min_r=0.25):
    """At `minutes` after entry, arm BE only if (a) the trade has
    previously reached >= min_r R favourably, and (b) the most recently
    completed bar closed on the profitable side of entry. Checked once
    minutes have elapsed; if not satisfied at that bar, kept checking
    every subsequent bar until satisfied (spec: 'at 15/30/45/60 minutes
    ... move the stop to entry only when' -- read as the earliest bar at
    or after the minute mark where both conditions hold)."""
    tb = _touch_bar_stop_check(bars, touch_ts, entry, sign, sl_dist)
    if tb is not None:
        return (*tb, {})
    rest = _path_arrays(bars, touch_ts, cutoff_ts)
    if rest.empty:
        return sign * (float(bars.loc[touch_ts, "close"]) - entry), "cutoff", touch_ts, {}

    orig_stop = entry - sign * sl_dist
    target = entry + sign * tp_dist
    hi, lo, cl = rest["high"].to_numpy(), rest["low"].to_numpy(), rest["close"].to_numpy()
    idx = rest.index

    running_max_fav = -np.inf
    ever_reached_min_r = False
    triggered_active = trigger_pending = False
    audit = {}

    for i in range(len(hi)):
        h, l, c = float(hi[i]), float(lo[i]), float(cl[i])
        if trigger_pending:
            triggered_active = True
            trigger_pending = False
            audit["trigger_activated_ts"] = idx[i]

        stop = entry if triggered_active else orig_stop

        if sign > 0:
            if l <= stop:
                return sign * (stop - entry), ("BE" if triggered_active else "SL"), idx[i], audit
            if h >= target:
                return tp_dist, "TP", idx[i], audit
            fav = h - entry
            closed_profitable = c >= entry
        else:
            if h >= stop:
                return sign * (stop - entry), ("BE" if triggered_active else "SL"), idx[i], audit
            if l <= target:
                return tp_dist, "TP", idx[i], audit
            fav = entry - l
            closed_profitable = c <= entry

        running_max_fav = max(running_max_fav, fav)
        if fav >= min_r * sl_dist:
            ever_reached_min_r = True

        minutes_elapsed = i + 1  # bars are 1-minute; bar i=0 is minute 1 after touch
        if not triggered_active and not trigger_pending:
            if minutes_elapsed >= minutes and ever_reached_min_r and closed_profitable:
                trigger_pending = True
                audit["trigger_bar_ts"] = idx[i]

    return sign * (float(cl[-1]) - entry), "cutoff", idx[-1], audit


def simulate_scratch_on_recovery(bars, touch_ts, cutoff_ts, entry, sign, tp_dist, sl_dist,
                                  adverse_r):
    """After adverse excursion reaches `adverse_r` R, arm a scratch watch
    (active from the NEXT bar). If price later returns to entry, exit at
    entry (scratch). Original TP/SL remain live and are checked first
    (SL > scratch > TP priority when ambiguous on one bar)."""
    tb = _touch_bar_stop_check(bars, touch_ts, entry, sign, sl_dist)
    if tb is not None:
        return (*tb, {})
    rest = _path_arrays(bars, touch_ts, cutoff_ts)
    if rest.empty:
        return sign * (float(bars.loc[touch_ts, "close"]) - entry), "cutoff", touch_ts, {}

    orig_stop = entry - sign * sl_dist
    target = entry + sign * tp_dist
    hi, lo, cl = rest["high"].to_numpy(), rest["low"].to_numpy(), rest["close"].to_numpy()
    idx = rest.index

    running_min_adv = np.inf   # most negative adverse R so far (adverse = negative)
    scratch_active = scratch_pending = False
    audit = {}

    for i in range(len(hi)):
        h, l = float(hi[i]), float(lo[i])
        if scratch_pending:
            scratch_active = True
            scratch_pending = False
            audit["scratch_armed_active_ts"] = idx[i]

        # original stop always checked first (never moved by scratch)
        if sign > 0:
            if l <= orig_stop:
                return sign * (orig_stop - entry), "SL", idx[i], audit
            if scratch_active and l <= entry <= h:
                return 0.0, "SCRATCH", idx[i], audit
            if h >= target:
                return tp_dist, "TP", idx[i], audit
            adv = l - entry
        else:
            if h >= orig_stop:
                return sign * (orig_stop - entry), "SL", idx[i], audit
            if scratch_active and l <= entry <= h:
                return 0.0, "SCRATCH", idx[i], audit
            if l <= target:
                return tp_dist, "TP", idx[i], audit
            adv = entry - h

        running_min_adv = min(running_min_adv, adv)
        if not scratch_active and not scratch_pending:
            if running_min_adv <= -adverse_r * sl_dist:
                scratch_pending = True
                audit["scratch_trigger_bar_ts"] = idx[i]

    return sign * (float(cl[-1]) - entry), "cutoff", idx[-1], audit


def simulate_combined_be_scratch(bars, touch_ts, cutoff_ts, entry, sign, tp_dist, sl_dist,
                                  be_r, scratch_r):
    """BE at +be_r R combined with scratch-on-recovery after -scratch_r R.
    Both mechanisms run concurrently: whichever bar first satisfies either
    trigger (net of next-bar activation) applies. Once BE has moved the
    stop to entry, the scratch-return-to-entry condition becomes
    redundant (both resolve to the same price) but is left active for
    consistency."""
    tb = _touch_bar_stop_check(bars, touch_ts, entry, sign, sl_dist)
    if tb is not None:
        return (*tb, {})
    rest = _path_arrays(bars, touch_ts, cutoff_ts)
    if rest.empty:
        return sign * (float(bars.loc[touch_ts, "close"]) - entry), "cutoff", touch_ts, {}

    orig_stop = entry - sign * sl_dist
    target = entry + sign * tp_dist
    hi, lo, cl = rest["high"].to_numpy(), rest["low"].to_numpy(), rest["close"].to_numpy()
    idx = rest.index

    running_max_fav = -np.inf
    running_min_adv = np.inf
    be_active = be_pending = False
    scratch_active = scratch_pending = False
    audit = {}

    for i in range(len(hi)):
        h, l = float(hi[i]), float(lo[i])
        if be_pending:
            be_active = True
            be_pending = False
            audit["be_activated_ts"] = idx[i]
        if scratch_pending:
            scratch_active = True
            scratch_pending = False
            audit["scratch_activated_ts"] = idx[i]

        stop = entry if be_active else orig_stop

        if sign > 0:
            if l <= stop:
                return sign * (stop - entry), ("BE" if be_active else "SL"), idx[i], audit
            if scratch_active and not be_active and l <= entry <= h:
                return 0.0, "SCRATCH", idx[i], audit
            if h >= target:
                return tp_dist, "TP", idx[i], audit
            fav, adv = h - entry, l - entry
        else:
            if h >= stop:
                return sign * (stop - entry), ("BE" if be_active else "SL"), idx[i], audit
            if scratch_active and not be_active and l <= entry <= h:
                return 0.0, "SCRATCH", idx[i], audit
            if l <= target:
                return tp_dist, "TP", idx[i], audit
            fav, adv = entry - l, entry - h

        running_max_fav = max(running_max_fav, fav)
        running_min_adv = min(running_min_adv, adv)
        if not be_active and not be_pending and running_max_fav >= be_r * sl_dist:
            be_pending = True
            audit["be_trigger_bar_ts"] = idx[i]
        if not scratch_active and not scratch_pending and running_min_adv <= -scratch_r * sl_dist:
            scratch_pending = True
            audit["scratch_trigger_bar_ts"] = idx[i]

    return sign * (float(cl[-1]) - entry), "cutoff", idx[-1], audit
