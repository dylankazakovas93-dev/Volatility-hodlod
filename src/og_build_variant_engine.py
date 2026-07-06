"""Parameterized variant of src.strict_engine for the OG build-four-years
research pipeline (Stages B-E). Additive only: src/strict_engine.py is
untouched and remains the canonical, frozen reference implementation. This
module imports its helpers directly and only adds toggles needed for a
controlled comparison:

  - sal_enabled: bool                  (Stage B)
  - be_bars: int                       (Stage C)
  - be_arm_requires_open_beyond: float (Stage C, optional extra profit-lock
                                         threshold layered on top of the BE-45
                                         open check)
  - entry_window: (start_min, end_min) blocked window in ET minutes-since-
                                         midnight, replacing the hardcoded
                                         11:00-15:00 block (Stage E)
  - hmm_gate: optional callable(ts) -> bool, applied at the same point as
                                         other entry gates; True = allow
                                         (Stage D)

Only OG_BUILD_YEARS (2018, 2020, 2023, 2026) may be used for any *outcome*
metric computed by callers of this module -- this module itself is agnostic
to which years are used, filtering happens in the caller (see
scripts/og_build_years_run.py).
"""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

from src.strict_engine import (
    ET, SL_CAP, BE_BARS,
    session_date, session_cutoff, prev_completed_range,
    touch_is_clean,
)
from src.metrics import profit_factor, max_drawdown, max_loss_streak

OG_BUILD_YEARS = {2018, 2020, 2023, 2026}


def entry_allowed_window(ts, blocked_start_min=11 * 60, blocked_end_min=15 * 60):
    et = ts.tz_convert(ET)
    m = et.hour * 60 + et.minute
    return not (blocked_start_min <= m < blocked_end_min)


def simulate_from_touch_variant(bars, touched_at, cutoff, entry_fill, sign, cap,
                                 be_bars=BE_BARS, be_extra_lock=0.0):
    """Same state machine as strict_engine.simulate_from_touch, with an
    optional additional profit-lock threshold (be_extra_lock, in points):
    once armed, the stop is placed at entry + sign*be_extra_lock instead of
    exactly at entry (0.0 reproduces the canonical BE-45 exactly)."""
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
    locked_stop = entry_fill + sign * be_extra_lock
    hi, lo, op, cl = (rest["high"].values, rest["low"].values, rest["open"].values, rest["close"].values)
    idx = rest.index
    armed = checked = False
    for i in range(len(hi)):
        h, l = float(hi[i]), float(lo[i])
        if i < be_bars:
            stop = orig_stop
        else:
            if not checked:
                checked = True
                o = float(op[i])
                armed = (o >= entry_fill) if sign > 0 else (o <= entry_fill)
            stop = locked_stop if armed else orig_stop
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
    return sign * (float(cl[-1]) - entry_fill), "cutoff", (idx[-1] if len(idx) else touched_at)


def run_variant(bars, ranges, events, *,
                 sal_enabled=True,
                 be_bars=BE_BARS,
                 be_extra_lock=0.0,
                 blocked_window=(11 * 60, 15 * 60),
                 hmm_gate=None,
                 tie_order="age"):
    """Chronological single-global-position engine identical in structure to
    strict_engine.run_strict, with the Stage B/C/D/E toggles applied. When
    all toggles are at canonical defaults this reproduces run_strict exactly
    (verified in scripts/og_build_years_run.py's self-check)."""
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

    pos_exit_time = None
    sal_session = None
    sal_armed_at = None

    def record_skip(ev, reason):
        skip_counts[reason] += 1

    for ts in sorted(groups.keys()):
        group = groups[ts]

        anchor = prev_completed_range(ranges, ts)
        if anchor is None:
            for e in group:
                record_skip(e, "no_anchor")
            continue

        if not entry_allowed_window(ts, *blocked_window):
            for e in group:
                record_skip(e, "blocked_time")
            continue

        if hmm_gate is not None and not hmm_gate(ts):
            for e in group:
                record_skip(e, "hmm_gate")
            continue

        cutoff = session_cutoff(ts)
        if cutoff is None:
            for e in group:
                record_skip(e, "no_cutoff")
            continue

        sess = session_date(ts)
        if sess != sal_session:
            sal_session = sess
            sal_armed_at = None

        if sal_enabled and sal_armed_at is not None and ts >= sal_armed_at:
            for e in group:
                record_skip(e, "SAL")
            continue

        if pos_exit_time is not None and ts < pos_exit_time:
            for e in group:
                record_skip(e, "position_open")
            continue
        if pos_exit_time is not None and ts == pos_exit_time:
            for e in group:
                record_skip(e, "same_bar_reentry")
            continue

        if len(group) > 1:
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
                record_skip(e, "simultaneous_collision")
        else:
            chosen = group[0]

        sign = -1.0 if chosen["side"] == "upper" else 1.0
        cap = min(1.5 * anchor, SL_CAP)
        clean = touch_is_clean(bars, ts, chosen["level"])
        fill = chosen["level"] if clean else float(bars.loc[ts, "close"])

        pnl, ex, exit_ts = simulate_from_touch_variant(
            bars, ts, cutoff, fill, sign, cap, be_bars=be_bars, be_extra_lock=be_extra_lock)

        year = pd.Timestamp(sess).year
        exit_price = fill + sign * pnl
        executed.append({
            "level_id": chosen["level_id"], "session_date": sess, "year": year,
            "side": chosen["side"], "entry_time": ts, "exit_time": exit_ts,
            "entry_price": fill, "exit_price": exit_price, "level": chosen["level"],
            "anchor": anchor, "cap": cap,
            "exit_reason": ex, "pnl": pnl, "gap_through": not clean,
        })

        pos_exit_time = exit_ts
        if pnl < -0.1 and ex != "BE":
            sal_armed_at = exit_ts

    ex_df = pd.DataFrame(executed)
    summary = {
        "total_physical_touches": total_physical_touches,
        "executed": len(ex_df),
        "skipped_SAL": skip_counts.get("SAL", 0),
        "skipped_position_open": skip_counts.get("position_open", 0),
        "skipped_hmm_gate": skip_counts.get("hmm_gate", 0),
        "skipped_blocked_time": skip_counts.get("blocked_time", 0),
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
            "avg_trade": round(float(pnl.mean()), 3),
            "max_drawdown": round(max_drawdown(pnl), 2),
            "max_loss_streak": max_loss_streak(ex_df["exit_reason"].tolist(), pnl.tolist()),
        })
    return summary, ex_df


def filter_build_years(ex_df, years=OG_BUILD_YEARS):
    """Filter an executed-trades dataframe to OG_BUILD_YEARS only. This is
    the ONLY function callers should use to compute outcome metrics in this
    research pipeline -- it is the data-firewall enforcement point."""
    if ex_df is None or len(ex_df) == 0:
        return ex_df
    return ex_df[ex_df["year"].isin(years)].copy()


def summarize(ex_df):
    if ex_df is None or len(ex_df) == 0:
        return {"n": 0}
    pnl = ex_df["pnl"]
    exs = ex_df["exit_reason"].value_counts()
    return {
        "n": len(ex_df),
        "net_pts": round(float(pnl.sum()), 2),
        "PF": round(profit_factor(pnl), 4),
        "win_rate": round(float((pnl > 0).mean()), 4),
        "avg_trade": round(float(pnl.mean()), 3),
        "max_drawdown": round(max_drawdown(pnl), 2),
        "TP": int(exs.get("TP", 0)), "SL": int(exs.get("SL", 0)),
        "BE": int(exs.get("BE", 0)), "cutoff": int(exs.get("cutoff", 0)),
    }
