#!/usr/bin/env python3
"""Independent second implementation of the frozen strict NQ mechanics.

This does NOT import or call anything from scripts/reconcile_strict_one_position.py
or scripts/nq_cond_be45.py's simulation/state-machine code. It reuses only
volgen.levels.generate_levels() (level-placement formula, load helpers) since
that is explicitly not one of the frozen execution mechanics under test.
Touch detection, session/window logic, anchor computation, the causal
single-position/SAL state machine, conditional BE, fill policy, and PF are
all written fresh here, independently, as a cross-check against
outputs/nq_strict_executed.csv.

Usage:
    python3 scripts/independent_nq_strict_engine.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv \
        --out-dir outputs
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from volgen.levels import NQ_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily

LINE_DAYS = 20
STOP_CAP = 200.0
BE_BAR = 45
ET = "America/New_York"


def valid_entry_window(ts):
    """19:00 ET -> 11:00 ET (next day) is the only valid entry window."""
    local = ts.tz_convert(ET)
    minute_of_day = local.hour * 60 + local.minute
    return minute_of_day >= 19 * 60 or minute_of_day < 11 * 60


def session_label(ts):
    """Sessions run 19:00 ET -> next-day 15:00 ET. A touch at/after 19:00 ET
    belongs to the *following* calendar day's session."""
    local = ts.tz_convert(ET)
    d = (local + pd.Timedelta(days=1)) if local.hour >= 19 else local
    return d.strftime("%Y-%m-%d")


def session_close_time(ts):
    """15:00 ET cutoff for the session that owns `ts`. Returns None for the
    dead zone 15:00-19:00 ET where no session is active."""
    local = ts.tz_convert(ET)
    day = local.strftime("%Y-%m-%d")
    close_today = pd.Timestamp(f"{day} 15:00", tz=ET)
    reopen_today = pd.Timestamp(f"{day} 19:00", tz=ET)
    if local < close_today:
        return close_today.tz_convert(ts.tz)
    if local >= reopen_today:
        tomorrow = (local.normalize() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        return pd.Timestamp(f"{tomorrow} 15:00", tz=ET).tz_convert(ts.tz)
    return None


def hourly_ranges(bars):
    hourly = bars.resample("60min", label="left", closed="left").agg(hi=("high", "max"), lo=("low", "min"))
    hourly = hourly.dropna()
    return (hourly["hi"] - hourly["lo"])


def anchor_range(ranges, ts):
    prior_hour = ts.floor("60min") - pd.Timedelta(hours=1)
    val = ranges.get(prior_hour)
    if val is None or pd.isna(val) or val <= 0:
        return None
    return float(val)


def scan_first_touch(bars_slice, level_value):
    """Independent touch scan: level inside [low, high], OR close crosses
    the level relative to the previous bar's close."""
    if bars_slice.empty:
        return None
    hi = bars_slice["high"].to_numpy()
    lo = bars_slice["low"].to_numpy()
    cl = bars_slice["close"].to_numpy()
    prior_cl = np.empty_like(cl)
    prior_cl[0] = np.nan
    prior_cl[1:] = cl[:-1]
    inside_range = (hi >= level_value) & (lo <= level_value)
    crossed_up = (cl >= level_value) & (prior_cl < level_value)
    crossed_dn = (cl <= level_value) & (prior_cl > level_value)
    hit = inside_range | crossed_up | crossed_dn
    idx = np.nonzero(hit)[0]
    if idx.size == 0:
        return None
    return bars_slice.index[idx[0]]


def build_touch_events(bars, level_rows):
    """One event per level side that is ever physically touched inside its
    live window (created_at, expiry) -- creation bar and expiry bar both
    excluded, matching the frozen no-creation-bar / expiry-excluded rules."""
    n = len(level_rows)
    events = []
    for i, lv in enumerate(level_rows):
        expiry_ts = level_rows[i + LINE_DAYS].created_at if i + LINE_DAYS < n else bars.index[-1]
        window = bars.loc[lv.created_at: expiry_ts]
        window = window[(window.index > lv.created_at) & (window.index < expiry_ts)]
        if window.empty:
            continue
        for side_name, level_value in (("upper", float(lv.upper_level)), ("lower", float(lv.lower_level))):
            touch_ts = scan_first_touch(window, level_value)
            if touch_ts is None:
                continue
            events.append({
                "level_id": f"{i}_{side_name}",
                "created_at": lv.created_at,
                "side": side_name,
                "level": level_value,
                "touch_ts": touch_ts,
            })
    return events


def bar_is_clean_touch(bars, ts, level_value):
    row = bars.loc[ts]
    return bool(row["low"] <= level_value <= row["high"])


def resolve_trade(bars, touch_ts, cutoff_ts, entry_px, direction, stop_dist):
    """direction: +1 for long, -1 for short. Returns (pnl, exit_reason, exit_ts)."""
    touch_bar = bars.loc[touch_ts]
    initial_stop = entry_px - direction * stop_dist
    target_px = entry_px + direction * stop_dist

    touch_hit_stop = (float(touch_bar["low"]) <= initial_stop) if direction > 0 else (float(touch_bar["high"]) >= initial_stop)
    if touch_hit_stop:
        pnl = direction * (initial_stop - entry_px)
        return pnl, "SL", touch_ts

    remaining = bars.loc[touch_ts: cutoff_ts].iloc[1:]
    if remaining.empty:
        pnl = direction * (float(touch_bar["close"]) - entry_px)
        return pnl, "cutoff", touch_ts

    highs = remaining["high"].to_numpy()
    lows = remaining["low"].to_numpy()
    opens = remaining["open"].to_numpy()
    closes = remaining["close"].to_numpy()
    times = remaining.index

    be_armed = False
    be_checked = False
    for j in range(len(highs)):
        bar_hi, bar_lo = float(highs[j]), float(lows[j])
        if j < BE_BAR:
            live_stop = initial_stop
        else:
            if not be_checked:
                be_checked = True
                open_px = float(opens[j])
                be_armed = (open_px >= entry_px) if direction > 0 else (open_px <= entry_px)
            live_stop = entry_px if be_armed else initial_stop

        if direction > 0:
            if bar_lo <= live_stop:
                reason = "BE" if (j >= BE_BAR and be_armed) else "SL"
                return direction * (live_stop - entry_px), reason, times[j]
            if bar_hi >= target_px:
                return stop_dist, "TP", times[j]
        else:
            if bar_hi >= live_stop:
                reason = "BE" if (j >= BE_BAR and be_armed) else "SL"
                return direction * (live_stop - entry_px), reason, times[j]
            if bar_lo <= target_px:
                return stop_dist, "TP", times[j]

    last_ts = times[-1] if len(times) else touch_ts
    last_close = float(closes[-1]) if len(closes) else float(touch_bar["close"])
    return direction * (last_close - entry_px), "cutoff", last_ts


def run_independent_engine(bars, ranges, events):
    by_ts = defaultdict(list)
    for e in events:
        by_ts[e["touch_ts"]].append(e)

    executed_rows = []
    skip_counter = defaultdict(int)

    position_open_until = None
    session_of_sal = None
    sal_blocked_from = None

    for ts in sorted(by_ts.keys()):
        candidates = by_ts[ts]

        anchor = anchor_range(ranges, ts)
        if anchor is None:
            skip_counter["no_anchor"] += len(candidates)
            continue

        if not valid_entry_window(ts):
            skip_counter["blocked_time"] += len(candidates)
            continue

        cutoff_ts = session_close_time(ts)
        if cutoff_ts is None:
            skip_counter["no_cutoff"] += len(candidates)
            continue

        this_session = session_label(ts)
        if this_session != session_of_sal:
            session_of_sal = this_session
            sal_blocked_from = None

        if sal_blocked_from is not None and ts >= sal_blocked_from:
            skip_counter["SAL"] += len(candidates)
            continue

        if position_open_until is not None and ts < position_open_until:
            skip_counter["position_open"] += len(candidates)
            continue
        if position_open_until is not None and ts == position_open_until:
            skip_counter["same_bar_reentry"] += len(candidates)
            continue

        # oldest-level-first deterministic tie-break
        candidates_sorted = sorted(candidates, key=lambda e: (e["created_at"], e["side"]))
        winner = candidates_sorted[0]
        for loser in candidates_sorted[1:]:
            skip_counter["simultaneous_collision"] += 1

        stop_dist = min(1.5 * anchor, STOP_CAP)
        direction = 1.0 if winner["side"] == "lower" else -1.0
        clean = bar_is_clean_touch(bars, ts, winner["level"])
        entry_px = winner["level"] if clean else float(bars.loc[ts, "close"])

        pnl, exit_reason, exit_ts = resolve_trade(bars, ts, cutoff_ts, entry_px, direction, stop_dist)
        exit_px = entry_px + direction * pnl

        session_year = pd.Timestamp(this_session).year
        executed_rows.append({
            "level_id": winner["level_id"], "session_date": this_session, "year": session_year,
            "side": winner["side"], "entry_time": ts, "exit_time": exit_ts,
            "entry_price": entry_px, "exit_price": exit_px, "anchor": anchor, "cap": stop_dist,
            "exit_reason": exit_reason, "pnl": pnl,
        })

        position_open_until = exit_ts
        if pnl < -0.1 and exit_reason != "BE":
            sal_blocked_from = exit_ts

    return pd.DataFrame(executed_rows), dict(skip_counter)


def profit_factor(pnl_series):
    gains = float(pnl_series[pnl_series > 0].sum())
    losses = float(-pnl_series[pnl_series < 0].sum())
    return gains / losses if losses > 0 else float("inf")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(repo_root, args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)
    levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    level_rows = list(levels.itertuples(index=False))
    ranges = hourly_ranges(bars)

    print("Building independent physical-touch table...")
    events = build_touch_events(bars, level_rows)
    print(f"  physical touches found: {len(events)}")

    print("Running independent causal single-position / time-aware-SAL engine...")
    ledger, skips = run_independent_engine(bars, ranges, events)
    ledger.to_csv(os.path.join(out_dir, "nq_independent_executed.csv"), index=False)

    exit_counts = ledger["exit_reason"].value_counts()
    pnl = ledger["pnl"]
    print(f"\n=== INDEPENDENT ENGINE RESULT ===")
    print(f"  executed        : {len(ledger)}")
    print(f"  net_pts         : {pnl.sum():.2f}")
    print(f"  PF              : {profit_factor(pnl):.4f}")
    print(f"  TP/SL/BE/cutoff : {int(exit_counts.get('TP',0))}/{int(exit_counts.get('SL',0))}/"
          f"{int(exit_counts.get('BE',0))}/{int(exit_counts.get('cutoff',0))}")
    yearly = ledger.groupby("year")["pnl"].sum()
    neg_years = sorted(int(y) for y, v in yearly.items() if v < 0)
    print(f"  negative years  : {neg_years}")
    print(f"  skip counts     : {skips}")


if __name__ == "__main__":
    main()
