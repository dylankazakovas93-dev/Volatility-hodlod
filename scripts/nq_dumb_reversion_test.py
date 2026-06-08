#!/usr/bin/env python3
"""Control test: does a context-free reversion strategy ("fade any X% intraday
move from the RTH open") show the same 2023-24 lose / 2025-26 win regime split
as the mu+/-k*sigma level strategy?

If yes -> the 2023-24 failure is a market-regime effect that hits reversion
strategies broadly, and the levels are "a smarter version of a real
phenomenon." If the dumb strategy is regime-agnostic (or the split looks
different), the levels' regime-dependence is more likely a curve-fit artifact
of where/how they happen to sample price.

Mechanics intentionally mirror the rest of the NQ study so the comparison is
apples-to-apples: enter on first touch of RTH-open +/- `--move-pct`, target/stop
sized off the prior completed N-minute range (TP = range*tp_mult, SL = TP/rr),
session exit at 15:00 ET / resume 19:00 ET, no entries 15:00-19:00.
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from volgen.levels import load_1m_ohlcv


def in_rth(index: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(
        ((index.hour > 9) | ((index.hour == 9) & (index.minute >= 30))) & (index.hour < 16),
        index=index,
    )


def rth_date(index: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(index.tz_convert("America/New_York").date.astype(str), index=index)


def rth_opens(bars: pd.DataFrame) -> pd.Series:
    rth = bars[in_rth(bars.index)]
    return rth.groupby(rth_date(rth.index))["open"].first()


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


def bar_ranges(bars: pd.DataFrame, range_minutes: int) -> pd.Series:
    ranged = bars.resample(f"{range_minutes}min", label="left", closed="left").agg({"high": "max", "low": "min"}).dropna()
    return ranged["high"] - ranged["low"]


def previous_completed_range(ranges: pd.Series, ts: pd.Timestamp, range_minutes: int) -> float | None:
    prev_start = ts.floor(f"{range_minutes}min") - pd.Timedelta(minutes=range_minutes)
    value = ranges.get(prev_start)
    if value is None or pd.isna(value) or value <= 0:
        return None
    return float(value)


def first_touch_of_level(day_bars: pd.DataFrame, level: float, side: str) -> pd.Timestamp | None:
    """side='down': first bar whose low <= level; side='up': first bar whose high >= level."""
    if side == "down":
        hit = day_bars[day_bars["low"] <= level]
    else:
        hit = day_bars[day_bars["high"] >= level]
    if hit.empty:
        return None
    return hit.index[0]


def simulate_fade(bars, sign, touched_at, entry, target_pts, stop_pts, cutoff_time, resume_time):
    """sign=+1 -> long (faded a downmove, expects reversion up); sign=-1 -> short."""
    future = bars.loc[touched_at:]
    if future.empty:
        return None
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
            hit_target, hit_stop = hi >= target, lo <= stop
        else:
            hit_target, hit_stop = lo <= target, hi >= stop
        if hit_stop:
            return -stop_pts
        if hit_target:
            return target_pts
    last_close = float(path["close"].iloc[-1])
    return sign * (last_close - entry)


def profit_factor(pts):
    pts = pd.Series(pts)
    gp = float(pts[pts > 0].sum())
    gl = float(-pts[pts < 0].sum())
    if gl == 0:
        return float("inf") if gp > 0 else 0.0
    return gp / gl


def run(bars, opens, ranges, move_pct, tp_mult, rr, range_minutes, cutoff_time, resume_time):
    rth = bars[in_rth(bars.index)]
    dates = sorted(opens.index)
    rows = []
    for date_key in dates:
        open_price = float(opens[date_key])
        day = rth[rth_date(rth.index).eq(date_key)]
        if day.empty:
            continue
        down_level = open_price * (1 - move_pct)
        up_level = open_price * (1 + move_pct)
        for side, level, sign in (("down", down_level, +1.0), ("up", up_level, -1.0)):
            touched_at = first_touch_of_level(day, level, side)
            if touched_at is None:
                continue
            anchor = previous_completed_range(ranges, touched_at, range_minutes)
            if anchor is None:
                continue
            target_pts = anchor * tp_mult
            stop_pts = target_pts / rr
            pts = simulate_fade(bars, sign, touched_at, level, target_pts, stop_pts, cutoff_time, resume_time)
            if pts is None:
                continue
            rows.append({"date_et": date_key, "side": side, "touched_at": touched_at, "pts": pts})
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", required=True)
    parser.add_argument("--move-pct", type=float, default=0.02, help="Fraction move from RTH open that triggers a fade entry (default 0.02 = 2%%)")
    parser.add_argument("--range-minutes", type=int, default=60)
    parser.add_argument("--tp-mult", type=float, default=0.5)
    parser.add_argument("--rr", type=float, default=0.75)
    parser.add_argument("--cutoff-time", default="15:00")
    parser.add_argument("--resume-time", default="19:00")
    args = parser.parse_args()

    bars = load_1m_ohlcv(args.bars)
    opens = rth_opens(bars)
    ranges = bar_ranges(bars, args.range_minutes)

    print(f"=== Dumb reversion control: fade any {args.move_pct*100:.1f}% intraday move from RTH open ===")
    print(f"TP = {args.tp_mult}x prior {args.range_minutes}min range, SL = TP/{args.rr}, session 19:00-15:00 ET\n")

    df = run(bars, opens, ranges, args.move_pct, args.tp_mult, args.rr, args.range_minutes, args.cutoff_time, args.resume_time)
    if df.empty:
        print("No touches found.")
        return

    df["year"] = pd.to_datetime(df["date_et"]).dt.year
    for year in sorted(df["year"].unique()):
        sub = df[df["year"] == year]["pts"]
        print(f"{year}: n={len(sub):3d}  net={sub.sum():9.2f}  win_rate={sub.gt(0).mean():.3f}  PF={profit_factor(sub):.3f}")

    print(f"\nAll years combined: n={len(df):3d}  net={df['pts'].sum():9.2f}  win_rate={df['pts'].gt(0).mean():.3f}  PF={profit_factor(df['pts']):.3f}")


if __name__ == "__main__":
    main()
