#!/usr/bin/env python3
"""Test: on NFP days, switch lower/upper-level logic to continuation only when
price has already moved >= `--threshold` x prior-14-session RTH ATR from the
RTH open at the moment of touch; otherwise trade the normal reversal (fade).

Combines 2025 + 2026 NFP days to maximize an inherently tiny sample (n~14-20),
and reports reversal-only / continuation-only / conditional side by side so the
conditional rule's claimed edge can be checked against what a coin flip on this
few trades would look like.

Session rule matches the rest of the NQ study: enter on first touch, hold to
TP/SL or the 15:00 ET cutoff, no entries 15:00-19:00 ET, resume at 19:00 ET.
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


def expansion_ratio_at_touch(bars: pd.DataFrame, touched_at: pd.Timestamp, open_price: float, prior_atr: float) -> float | None:
    if prior_atr <= 0 or pd.isna(prior_atr):
        return None
    date_key = touched_at.tz_convert("America/New_York").strftime("%Y-%m-%d")
    day = bars[in_rth(bars.index)]
    day = day[rth_date(day.index).eq(date_key)]
    path = day.loc[:touched_at]
    if path.empty:
        return None
    max_move = max(float((path["high"] - open_price).abs().max()), float((path["low"] - open_price).abs().max()))
    return max_move / float(prior_atr)


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


def direction_for(side: str, logic: str) -> float:
    if logic == "reversal":
        return 1.0 if side == "lower" else -1.0
    return -1.0 if side == "lower" else 1.0


def simulate(bars, side, logic, touched_at, level, anchor_range, tp_mult, rr, cutoff_time, resume_time):
    future = bars.loc[touched_at:]
    if future.empty:
        return None
    sign = direction_for(side, logic)
    entry = float(level)
    target_pts = anchor_range * tp_mult
    stop_pts = target_pts / rr
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


def load_event_dates(paths, event_type):
    dates = set()
    for path in paths:
        df = pd.read_csv(path)
        dates |= set(df.loc[df["event_type"] == event_type, "date"].astype(str))
    return dates


def bar_ranges(bars, range_minutes):
    ranged = bars.resample(f"{range_minutes}min", label="left", closed="left").agg({"high": "max", "low": "min"}).dropna()
    return ranged["high"] - ranged["low"]


def previous_completed_range(ranges, ts, range_minutes):
    prev_start = ts.floor(f"{range_minutes}min") - pd.Timedelta(minutes=range_minutes)
    value = ranges.get(prev_start)
    if value is None or pd.isna(value) or value <= 0:
        return None
    return float(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", required=True)
    parser.add_argument("--vxn", default="data/vxn_daily.csv")
    parser.add_argument("--events", nargs="+", default=["data/nq_2025_event_days.csv", "data/nq_2026_event_days.csv"])
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2026-06-07")
    parser.add_argument("--threshold", type=float, default=1.5)
    parser.add_argument("--atr-len", type=int, default=14)
    parser.add_argument("--range-minutes", type=int, default=60)
    parser.add_argument("--tp-mult", type=float, default=0.5)
    parser.add_argument("--rr", type=float, default=0.75)
    parser.add_argument("--cutoff-time", default="15:00")
    parser.add_argument("--resume-time", default="19:00")
    args = parser.parse_args()

    bars = load_1m_ohlcv(args.bars)
    bars = bars[(bars.index.date >= pd.Timestamp(args.start).date()) & (bars.index.date <= pd.Timestamp(args.end).date())]
    vxn = load_gvz_daily(args.vxn)
    levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges = bar_ranges(bars, args.range_minutes)
    atr = completed_rth_atr(bars, args.atr_len)
    opens = rth_opens(bars)
    nfp_dates = load_event_dates(args.events, "nfp")
    print(f"NFP dates loaded: {sorted(nfp_dates)}")

    rows = []
    search_window = pd.Timedelta(days=5)
    for _, row in levels.iterrows():
        for side, level_col in (("lower", "lower_level"), ("upper", "upper_level")):
            level = float(row[level_col])
            window = bars.loc[row["created_at"] : row["created_at"] + search_window]
            touched_at = _first_touch(window, level)
            if touched_at is None:
                continue
            date_key = touched_at.tz_convert("America/New_York").strftime("%Y-%m-%d")
            if date_key not in nfp_dates:
                continue
            anchor_range = previous_completed_range(ranges, touched_at, args.range_minutes)
            if anchor_range is None:
                continue
            prior_atr = atr.get(date_key)
            open_price = opens.get(date_key)
            expansion = None
            if open_price is not None and prior_atr is not None and not pd.isna(prior_atr):
                expansion = expansion_ratio_at_touch(bars, touched_at, float(open_price), float(prior_atr))

            rev_pts = simulate(bars, side, "reversal", touched_at, level, anchor_range, args.tp_mult, args.rr, args.cutoff_time, args.resume_time)
            cont_pts = simulate(bars, side, "continuation", touched_at, level, anchor_range, args.tp_mult, args.rr, args.cutoff_time, args.resume_time)
            if rev_pts is None or cont_pts is None:
                continue
            rows.append(
                {
                    "date_et": date_key,
                    "side": side,
                    "touched_at": touched_at,
                    "expansion_ratio": expansion,
                    "reversal_pts": rev_pts,
                    "continuation_pts": cont_pts,
                }
            )

    df = pd.DataFrame(rows).sort_values("touched_at")
    if df.empty:
        print("No NFP touches found.")
        return

    df["conditional_pts"] = df.apply(
        lambda r: r["continuation_pts"] if (r["expansion_ratio"] is not None and r["expansion_ratio"] >= args.threshold) else r["reversal_pts"],
        axis=1,
    )
    df["conditional_logic"] = df.apply(
        lambda r: "continuation" if (r["expansion_ratio"] is not None and r["expansion_ratio"] >= args.threshold) else "reversal",
        axis=1,
    )

    print(f"\n=== NFP TOUCHES: {len(df)} (2025 + 2026 combined, threshold={args.threshold}x ATR) ===")
    print(df[["date_et", "side", "expansion_ratio", "reversal_pts", "continuation_pts", "conditional_logic", "conditional_pts"]].to_string(index=False))

    for label, col in (("always reversal", "reversal_pts"), ("always continuation", "continuation_pts"), (f"conditional ({args.threshold}x ATR)", "conditional_pts")):
        pts = df[col]
        print(
            f"\n{label:28s} n={len(pts):2d}  net={pts.sum():9.2f}  win_rate={pts.gt(0).mean():.2f}  PF={profit_factor(pts):.3f}"
        )
    n_cont = (df["conditional_logic"] == "continuation").sum()
    print(f"\nConditional rule fired 'continuation' on {n_cont}/{len(df)} touches (expansion >= {args.threshold}x ATR at touch).")


if __name__ == "__main__":
    main()
