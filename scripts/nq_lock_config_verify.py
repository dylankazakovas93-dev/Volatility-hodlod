#!/usr/bin/env python3
"""Verify Codex's lock-config sweep results.

Config under test (Codex's "Top Lock Candidate"):
  - 60-min anchor range
  - TP = 1.5x prior 1h range
  - RR = 1.0 (SL = TP, equal risk:reward)
  - Entry window: 19:00 ET -> 11:00 ET only (skip late-RTH 11:00-15:00)
  - Exit cutoff: 15:00 ET / resume 19:00 ET (unchanged)
  - Lower-level ATR flip: if lower level touched with downside expansion >= 1.3x
    prior-14-session RTH ATR from RTH open, flip to short continuation
  - CPI continuation (all other events: reversal)
  - Risk: stop after first losing trade of the day

Simple Control (no ATR flip, pure reversal, same time/target params) is also
reported for comparison.

Runs in-sample years (2021, 2023, 2024, 2025, 2026) and OOS year (2022).
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from volgen.levels import NQ_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.reactions import _first_touch


def in_rth(index: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(
        ((index.hour > 9) | ((index.hour == 9) & (index.minute >= 30))) & (index.hour < 16),
        index=index,
    )


def rth_date(index: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(index.tz_convert("America/New_York").date.astype(str), index=index)


def completed_rth_atr(bars: pd.DataFrame, atr_len: int) -> pd.Series:
    rth = bars[in_rth(bars.index)]
    dates = rth_date(rth.index)
    daily = rth.groupby(dates).agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    prev_close = daily["close"].shift(1)
    tr = pd.concat(
        [daily["high"] - daily["low"], (daily["high"] - prev_close).abs(), (daily["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(atr_len, min_periods=atr_len).mean().shift(1)


def rth_opens(bars: pd.DataFrame) -> pd.Series:
    rth = bars[in_rth(bars.index)]
    return rth.groupby(rth_date(rth.index))["open"].first()


def downside_expansion_at_touch(bars, touched_at, open_price, prior_atr):
    if prior_atr <= 0 or pd.isna(prior_atr):
        return None
    date_key = touched_at.tz_convert("America/New_York").strftime("%Y-%m-%d")
    rth = bars[in_rth(bars.index)]
    day = rth[rth_date(rth.index).eq(date_key)]
    path = day.loc[:touched_at]
    if path.empty:
        return None
    max_down = float((open_price - path["low"]).max())
    return max_down / float(prior_atr)


def bar_ranges(bars: pd.DataFrame, range_minutes: int) -> pd.Series:
    ranged = bars.resample(f"{range_minutes}min", label="left", closed="left").agg({"high": "max", "low": "min"}).dropna()
    return ranged["high"] - ranged["low"]


def previous_completed_range(ranges: pd.Series, ts: pd.Timestamp, range_minutes: int) -> float | None:
    prev_start = ts.floor(f"{range_minutes}min") - pd.Timedelta(minutes=range_minutes)
    v = ranges.get(prev_start)
    if v is None or pd.isna(v) or v <= 0:
        return None
    return float(v)


def session_cutoff(touched_at: pd.Timestamp, cutoff_time: str, resume_time: str) -> pd.Timestamp | None:
    touched_et = touched_at.tz_convert("America/New_York")
    touch_date = touched_et.strftime("%Y-%m-%d")
    same_day_cutoff = pd.Timestamp(f"{touch_date} {cutoff_time}", tz="America/New_York")
    same_day_resume = pd.Timestamp(f"{touch_date} {resume_time}", tz="America/New_York")
    if touched_et < same_day_cutoff:
        return same_day_cutoff.tz_convert(touched_at.tz)
    if touched_et >= same_day_resume:
        next_day = touched_et.normalize() + pd.Timedelta(days=1)
        next_cutoff = pd.Timestamp(f"{next_day.strftime('%Y-%m-%d')} {cutoff_time}", tz="America/New_York")
        return next_cutoff.tz_convert(touched_at.tz)
    return None


def entry_allowed(touched_at: pd.Timestamp, entry_cutoff_time: str) -> bool:
    """Return False if touch falls in the skipped late-RTH window (entry_cutoff_time to 15:00 ET)."""
    et = touched_at.tz_convert("America/New_York")
    cutoff_h, cutoff_m = map(int, entry_cutoff_time.split(":"))
    cutoff_minutes = cutoff_h * 60 + cutoff_m
    touch_minutes = et.hour * 60 + et.minute
    # Skip entries between entry_cutoff and 15:00 ET
    if cutoff_minutes <= touch_minutes < 15 * 60:
        return False
    return True


def simulate(bars, sign, touched_at, level, target_pts, stop_pts, cutoff_time, resume_time):
    future = bars.loc[touched_at:]
    if future.empty:
        return None
    entry = float(level)
    target = entry + sign * target_pts
    stop = entry - sign * stop_pts
    cutoff = session_cutoff(touched_at, cutoff_time, resume_time)
    if cutoff is None:
        return None
    path = future.loc[:cutoff].iloc[1:]
    if path.empty:
        return None
    for _, bar in path.iterrows():
        hi, lo = float(bar["high"]), float(bar["low"])
        if sign > 0:
            ht, hs = hi >= target, lo <= stop
        else:
            ht, hs = lo <= target, hi >= stop
        if hs:
            return -stop_pts
        if ht:
            return target_pts
    return sign * (float(path["close"].iloc[-1]) - entry)


def load_events(paths):
    events = {}
    for path in paths:
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path)
        for _, row in df.iterrows():
            d = str(row["date"])
            et = str(row["event_type"])
            events.setdefault(d, set()).add(et)
    return events


def apply_stop_after_loss(records):
    df = pd.DataFrame(records).sort_values("touched_at")
    kept = []
    for _, day in df.groupby("date_et"):
        for _, row in day.iterrows():
            kept.append(row.to_dict())
            if row["pts"] < 0:
                break
    return kept


def profit_factor(pts):
    pts = pd.Series(pts)
    gp = float(pts[pts > 0].sum())
    gl = float(-pts[pts < 0].sum())
    if gl == 0:
        return float("inf") if gp > 0 else 0.0
    return gp / gl


def max_drawdown(pts):
    pts = pd.Series(pts)
    if pts.empty:
        return 0.0
    eq = pts.cumsum()
    return float((eq - eq.cummax()).min())


def print_results(kept, label):
    if not kept:
        print(f"  {label}: no trades")
        return
    df = pd.DataFrame(kept)
    years = sorted(df["year"].unique())
    for yr in years:
        sub = df[df["year"] == yr]["pts"]
        print(f"  {yr}: n={len(sub):3d}  net={sub.sum():9.2f}  PF={profit_factor(sub):.3f}  maxDD={max_drawdown(sub):.2f}")
    pts = df["pts"]
    wr = float((pts > 0).mean())
    print(f"  ALL : n={len(pts):3d}  net={pts.sum():9.2f}  PF={profit_factor(pts):.3f}  WR={wr:.3f}  maxDD={max_drawdown(pts):.2f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", required=True)
    parser.add_argument("--vxn", default="data/vxn_daily_2020_2026.csv")
    parser.add_argument("--events", nargs="+", default=[
        "data/nq_2021_event_days.csv",
        "data/nq_2022_event_days.csv",
        "data/nq_2023_event_days.csv",
        "data/nq_2024_event_days.csv",
        "data/nq_2025_event_days.csv",
        "data/nq_2026_event_days.csv",
    ])
    parser.add_argument("--in-sample-years", default="2021,2023,2024,2025,2026")
    parser.add_argument("--oos-year", default="2022")
    parser.add_argument("--tp-mult", type=float, default=1.5)
    parser.add_argument("--rr", type=float, default=1.0)
    parser.add_argument("--range-minutes", type=int, default=60)
    parser.add_argument("--entry-cutoff-time", default="11:00", help="Skip entries at/after this ET time until 15:00")
    parser.add_argument("--cutoff-time", default="15:00")
    parser.add_argument("--resume-time", default="19:00")
    parser.add_argument("--atr-flip-threshold", type=float, default=1.3)
    parser.add_argument("--atr-len", type=int, default=14)
    args = parser.parse_args()

    in_sample = {int(y) for y in args.in_sample_years.split(",")}
    oos_year = int(args.oos_year)

    bars = load_1m_ohlcv(args.bars)
    vxn = load_gvz_daily(args.vxn)
    events = load_events(args.events)

    levels_all = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges = bar_ranges(bars, args.range_minutes)
    atr = completed_rth_atr(bars, args.atr_len)
    opens = rth_opens(bars)

    search_window = pd.Timedelta(days=5)
    raw = []
    for _, row in levels_all.iterrows():
        for side, col in (("lower", "lower_level"), ("upper", "upper_level")):
            level = float(row[col])
            window = bars.loc[row["created_at"]: row["created_at"] + search_window]
            touched_at = _first_touch(window, level)
            if touched_at is None:
                continue
            if not entry_allowed(touched_at, args.entry_cutoff_time):
                continue
            date_key = touched_at.tz_convert("America/New_York").strftime("%Y-%m-%d")
            year = touched_at.tz_convert("America/New_York").year
            anchor = previous_completed_range(ranges, touched_at, args.range_minutes)
            if anchor is None:
                continue
            target_pts = anchor * args.tp_mult
            stop_pts = target_pts / args.rr

            event_types = events.get(date_key, set())
            is_cpi = "cpi" in event_types

            # reversal sign: lower=+1 (long), upper=-1 (short)
            rev_sign = 1.0 if side == "lower" else -1.0

            # ATR flip for lower levels
            expansion = None
            if side == "lower":
                prior_atr = atr.get(date_key)
                open_price = opens.get(date_key)
                if prior_atr is not None and not pd.isna(prior_atr) and open_price is not None:
                    expansion = downside_expansion_at_touch(bars, touched_at, float(open_price), float(prior_atr))

            flip_short = (side == "lower" and expansion is not None and expansion >= args.atr_flip_threshold)

            # Simulate reversal and (if applicable) continuation
            rev_pts = simulate(bars, rev_sign, touched_at, level, target_pts, stop_pts, args.cutoff_time, args.resume_time)
            if rev_pts is None:
                continue

            # Top config: ATR flip + CPI continuation
            if flip_short:
                top_pts = simulate(bars, -rev_sign, touched_at, level, target_pts, stop_pts, args.cutoff_time, args.resume_time)
                if top_pts is None:
                    top_pts = rev_pts
            elif is_cpi:
                cont_pts = simulate(bars, -rev_sign, touched_at, level, target_pts, stop_pts, args.cutoff_time, args.resume_time)
                top_pts = cont_pts if cont_pts is not None else rev_pts
            else:
                top_pts = rev_pts

            raw.append({
                "date_et": date_key,
                "year": year,
                "side": side,
                "touched_at": touched_at,
                "expansion": expansion,
                "is_cpi": is_cpi,
                "flip_short": flip_short,
                "rev_pts": rev_pts,
                "top_pts": top_pts,
            })

    print(f"Total touches (entry filter applied): {len(raw)}")

    for label, col, years_set, header in [
        ("Simple Control (pure reversal, no flip/CPI)", "rev_pts", in_sample, "IN-SAMPLE"),
        ("Top Config (ATR flip + CPI cont)", "top_pts", in_sample, "IN-SAMPLE"),
        ("Simple Control OOS 2022", "rev_pts", {oos_year}, "OOS"),
        ("Top Config OOS 2022", "top_pts", {oos_year}, "OOS"),
    ]:
        subset = [r for r in raw if r["year"] in years_set]
        records = [{"date_et": r["date_et"], "year": r["year"], "touched_at": r["touched_at"], "pts": r[col]} for r in subset]
        kept = apply_stop_after_loss(records)
        print(f"\n=== {header}: {label} ===")
        print_results(kept, label)

    # Summary of flip activity
    flips = [r for r in raw if r["flip_short"]]
    print(f"\nATR flip fired on {len(flips)} touches across all years.")
    if flips:
        flip_df = pd.DataFrame(flips)
        for yr in sorted(flip_df["year"].unique()):
            n = len(flip_df[flip_df["year"] == yr])
            print(f"  {yr}: {n} flips")


if __name__ == "__main__":
    main()
