#!/usr/bin/env python3
"""Formal dumb-reversion control: exactly mirrors the real strategy session/exit rules.

Session: 19:00 ET -> 15:00 ET (resume after 19:00, same as real strategy).
Entry: first bar whose low/high crosses RTH open +/- threshold%.
TP/SL: same bracket shape (TP = tp_mult * prior N-min range, SL = TP/rr).
Risk: stop after first losing trade of the day.
Breakdown: by year, threshold, direction (long-reversion / short-reversion),
           and time bucket (pre-RTH / early-RTH / late-RTH).

Diagnostic: did custom levels outperform generic % reversion in same years/session?
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from volgen.levels import load_1m_ohlcv


def rth_date_str(ts: pd.Timestamp) -> str:
    return ts.tz_convert("America/New_York").strftime("%Y-%m-%d")


def rth_opens(bars: pd.DataFrame) -> pd.Series:
    et = bars.index.tz_convert("America/New_York")
    rth_mask = ((et.hour > 9) | ((et.hour == 9) & (et.minute >= 30))) & (et.hour < 16)
    rth = bars[rth_mask]
    dates = pd.Series(et[rth_mask].date.astype(str), index=rth.index)
    return rth.groupby(dates)["open"].first()


def time_bucket(ts: pd.Timestamp) -> str:
    et = ts.tz_convert("America/New_York")
    h, m = et.hour, et.minute
    if (h < 9) or (h == 9 and m < 30):
        return "pre_rth"
    if h < 12:
        return "early_rth"
    return "late_rth"


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
    v = ranges.get(prev_start)
    if v is None or pd.isna(v) or v <= 0:
        return None
    return float(v)


def simulate(bars, sign, touched_at, entry, target_pts, stop_pts, cutoff_time, resume_time):
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
            ht, hs = hi >= target, lo <= stop
        else:
            ht, hs = lo <= target, hi >= stop
        if hs:
            return -stop_pts
        if ht:
            return target_pts
    return sign * (float(path["close"].iloc[-1]) - entry)


def profit_factor(pts: pd.Series) -> float:
    gp = float(pts[pts > 0].sum())
    gl = float(-pts[pts < 0].sum())
    if gl == 0:
        return float("inf") if gp > 0 else 0.0
    return gp / gl


def max_drawdown(pts: pd.Series) -> float:
    if pts.empty:
        return 0.0
    eq = pts.cumsum()
    return float((eq - eq.cummax()).min())


def apply_stop_after_loss(df: pd.DataFrame) -> pd.DataFrame:
    kept = []
    for _, day in df.sort_values("touched_at").groupby("date_et"):
        for _, row in day.iterrows():
            kept.append(row)
            if row["pts"] < 0:
                break
    return pd.DataFrame(kept)


def print_year_table(df: pd.DataFrame, label: str) -> None:
    if df.empty:
        print(f"  {label}: no trades")
        return
    for yr in sorted(df["year"].unique()):
        sub = df[df["year"] == yr]["pts"]
        print(f"  {yr}: n={len(sub):4d}  net={sub.sum():9.2f}  PF={profit_factor(sub):.3f}  maxDD={max_drawdown(sub):.2f}")
    pts = df["pts"]
    print(f"  ALL : n={len(pts):4d}  net={pts.sum():9.2f}  PF={profit_factor(pts):.3f}  maxDD={max_drawdown(pts):.2f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", required=True)
    parser.add_argument("--thresholds", default="0.005,0.0075,0.01,0.0125,0.015,0.02")
    parser.add_argument("--range-minutes", type=int, default=60)
    parser.add_argument("--tp-mult", type=float, default=0.5)
    parser.add_argument("--rr", type=float, default=0.75)
    parser.add_argument("--cutoff-time", default="15:00")
    parser.add_argument("--resume-time", default="19:00")
    parser.add_argument("--out", default="/tmp/dumb_formal.csv")
    args = parser.parse_args()

    bars = load_1m_ohlcv(args.bars)
    opens = rth_opens(bars)
    ranges = bar_ranges(bars, args.range_minutes)
    thresholds = [float(x) for x in args.thresholds.split(",")]

    # Build all raw touches: for each session date, for each threshold,
    # find first bar crossing open +/- threshold% in full session window.
    session_dates = sorted(opens.index)
    records = []
    for date_key in session_dates:
        open_price = float(opens[date_key])
        # Session window: prior 19:00 ET to this day's 15:00 ET
        dt = pd.Timestamp(date_key, tz="America/New_York")
        session_start = (dt - pd.Timedelta(days=1)).replace(hour=19, minute=0, second=0)
        session_end = dt.replace(hour=15, minute=0, second=0)
        session_bars = bars.loc[session_start:session_end]
        if session_bars.empty:
            continue

        for threshold in thresholds:
            down_level = open_price * (1 - threshold)
            up_level = open_price * (1 + threshold)

            # Long-reversion: first touch of down_level (price fell, fade long)
            down_hits = session_bars[session_bars["low"] <= down_level]
            if not down_hits.empty:
                touched_at = down_hits.index[0]
                anchor = previous_completed_range(ranges, touched_at, args.range_minutes)
                if anchor is not None:
                    target_pts = args.tp_mult * anchor
                    stop_pts = target_pts / args.rr
                    pts = simulate(bars, +1.0, touched_at, down_level, target_pts, stop_pts, args.cutoff_time, args.resume_time)
                    if pts is not None:
                        records.append({
                            "date_et": date_key,
                            "year": dt.year,
                            "threshold_pct": threshold * 100,
                            "direction": "long_reversion",
                            "bucket": time_bucket(touched_at),
                            "touched_at": touched_at,
                            "pts": pts,
                        })

            # Short-reversion: first touch of up_level (price rose, fade short)
            up_hits = session_bars[session_bars["high"] >= up_level]
            if not up_hits.empty:
                touched_at = up_hits.index[0]
                anchor = previous_completed_range(ranges, touched_at, args.range_minutes)
                if anchor is not None:
                    target_pts = args.tp_mult * anchor
                    stop_pts = target_pts / args.rr
                    pts = simulate(bars, -1.0, touched_at, up_level, target_pts, stop_pts, args.cutoff_time, args.resume_time)
                    if pts is not None:
                        records.append({
                            "date_et": date_key,
                            "year": dt.year,
                            "threshold_pct": threshold * 100,
                            "direction": "short_reversion",
                            "bucket": time_bucket(touched_at),
                            "touched_at": touched_at,
                            "pts": pts,
                        })

    df_all = pd.DataFrame(records)
    if df_all.empty:
        print("No trades found.")
        return
    df_all.to_csv(args.out, index=False)
    print(f"Raw touches written to {args.out}: {len(df_all)} rows")

    for threshold in thresholds:
        sub = df_all[df_all["threshold_pct"].eq(threshold * 100)].copy()
        if sub.empty:
            continue
        pct_label = f"{threshold*100:.2f}%"
        print(f"\n{'='*60}")
        print(f"THRESHOLD: {pct_label} from RTH open")
        print(f"{'='*60}")

        for direction in ("long_reversion", "short_reversion"):
            d = sub[sub["direction"].eq(direction)].copy()
            d_sal = apply_stop_after_loss(d)
            label = "Long fade (buy dip)" if direction == "long_reversion" else "Short fade (sell rip)"
            print(f"\n  {label} + stop_after_loss:")
            print_year_table(d_sal, label)

            print(f"\n    By time bucket (all years, stop_after_loss):")
            for bucket in ("pre_rth", "early_rth", "late_rth"):
                bsub = d_sal[d_sal["bucket"].eq(bucket)]["pts"] if not d_sal.empty else pd.Series(dtype=float)
                if bsub.empty:
                    continue
                print(f"      {bucket:12s}: n={len(bsub):4d}  net={bsub.sum():9.2f}  PF={profit_factor(bsub):.3f}")


if __name__ == "__main__":
    main()
