#!/usr/bin/env python3
"""Dumb intraday NQ reversion baseline.

This intentionally ignores the VDL levels. It asks whether generic intraday
mean reversion also flips from 2023-2024 to 2025-2026.

Entry variants:
- pullback_long: first low <= RTH open * (1 - threshold)
- rally_short: first high >= RTH open * (1 + threshold)
- both: take the first of either threshold breach

Exit uses the same bracket convention as the NQ level tests:
TP = tp_mult * previous completed range_minutes high-low range
SL = TP / rr
and exits at the cutoff time if neither bracket is hit.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.nq_event_mode_study import (
    bar_ranges,
    previous_completed_range,
    profit_factor,
)
from volgen.levels import load_1m_ohlcv


@dataclass(frozen=True)
class Trade:
    year: int
    date_et: str
    mode: str
    threshold_pct: float
    touched_at: pd.Timestamp
    entry: float
    direction: str
    anchor_range: float
    target_pts: float
    stop_pts: float
    result: str
    bars_held: int
    pts: float


def first_trigger(day: pd.DataFrame, open_price: float, threshold: float, mode: str) -> tuple[pd.Timestamp, float, str] | None:
    long_level = open_price * (1.0 - threshold)
    short_level = open_price * (1.0 + threshold)
    candidates = []
    if mode in {"pullback_long", "both"}:
        hits = day[day["low"] <= long_level]
        if not hits.empty:
            candidates.append((hits.index[0], long_level, "long"))
    if mode in {"rally_short", "both"}:
        hits = day[day["high"] >= short_level]
        if not hits.empty:
            candidates.append((hits.index[0], short_level, "short"))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0]


def simulate_exit(
    bars: pd.DataFrame,
    touched_at: pd.Timestamp,
    entry: float,
    direction: str,
    target_pts: float,
    stop_pts: float,
    cutoff_time: str,
) -> tuple[str, int, float]:
    sign = 1.0 if direction == "long" else -1.0
    target = entry + sign * target_pts
    stop = entry - sign * stop_pts
    touched_et = touched_at.tz_convert("America/New_York")
    cutoff = pd.Timestamp(f"{touched_et.strftime('%Y-%m-%d')} {cutoff_time}", tz="America/New_York")
    cutoff = cutoff.tz_convert(touched_at.tz)
    path = bars.loc[touched_at:cutoff]
    if path.empty:
        return "no_path", 0, 0.0

    # Skip the trigger bar for bracket checks, matching the level-study
    # assumption that 1m OHLC cannot order the trigger vs bracket path inside
    # the same bar.
    for i, (_, row) in enumerate(path.iloc[1:].iterrows(), start=1):
        if direction == "long":
            hit_tp = row["high"] >= target
            hit_sl = row["low"] <= stop
        else:
            hit_tp = row["low"] <= target
            hit_sl = row["high"] >= stop
        if hit_tp and hit_sl:
            return "ambiguous_stop", i, -stop_pts
        if hit_tp:
            return "target", i, target_pts
        if hit_sl:
            return "stop", i, -stop_pts

    last = float(path["close"].iloc[-1])
    return "cutoff", max(len(path) - 1, 0), sign * (last - entry)


def max_drawdown(pts: pd.Series) -> float:
    if pts.empty:
        return 0.0
    equity = pts.cumsum()
    return float((equity - equity.cummax()).min())


def summarize(df: pd.DataFrame, year: str, mode: str, threshold: float) -> dict[str, object]:
    pts = df["pts"] if not df.empty else pd.Series(dtype=float)
    monthly = df.groupby(df["touched_at"].dt.tz_convert("America/New_York").dt.strftime("%Y-%m"))["pts"].sum() if not df.empty else pd.Series(dtype=float)
    return {
        "year": year,
        "mode": mode,
        "threshold_pct": threshold * 100.0,
        "trades": len(df),
        "net_points": float(pts.sum()) if not pts.empty else 0.0,
        "win_rate": float(pts.gt(0).mean()) if not pts.empty else float("nan"),
        "profit_factor": profit_factor(pts) if not pts.empty else float("nan"),
        "max_drawdown": max_drawdown(pts) if not pts.empty else 0.0,
        "worst_month": float(monthly.min()) if not monthly.empty else 0.0,
        "negative_months": int((monthly < 0).sum()) if not monthly.empty else 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", nargs="+", required=True)
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--end", default="2026-06-07")
    parser.add_argument("--thresholds", default="0.01,0.015,0.02,0.025")
    parser.add_argument("--modes", default="pullback_long,rally_short,both")
    parser.add_argument("--range-minutes", type=int, default=60)
    parser.add_argument("--tp-mult", type=float, default=0.5)
    parser.add_argument("--rr", type=float, default=0.75)
    parser.add_argument("--cutoff-time", default="15:00")
    parser.add_argument("--out-prefix", default="out/nq_dumb_reversion_regime")
    args = parser.parse_args()

    bars = pd.concat([load_1m_ohlcv(path) for path in args.bars]).sort_index()
    bars = bars[~bars.index.duplicated(keep="first")]
    bars = bars[(bars.index.date >= pd.Timestamp(args.start).date()) & (bars.index.date <= pd.Timestamp(args.end).date())]
    ranges = bar_ranges(bars, args.range_minutes)
    thresholds = [float(part) for part in args.thresholds.split(",") if part.strip()]
    modes = [part.strip() for part in args.modes.split(",") if part.strip()]

    records = []
    rth = bars.between_time("09:30", args.cutoff_time)
    for day_date, day in rth.groupby(rth.index.date):
        if day.empty:
            continue
        open_price = float(day["open"].iloc[0])
        for threshold in thresholds:
            for mode in modes:
                trigger = first_trigger(day, open_price, threshold, mode)
                if trigger is None:
                    continue
                touched_at, entry, direction = trigger
                anchor_range = previous_completed_range(ranges, touched_at, args.range_minutes)
                if anchor_range is None:
                    continue
                target_pts = args.tp_mult * anchor_range
                stop_pts = target_pts / args.rr
                result, bars_held, pts = simulate_exit(bars, touched_at, entry, direction, target_pts, stop_pts, args.cutoff_time)
                records.append(
                    Trade(
                        year=touched_at.tz_convert("America/New_York").year,
                        date_et=touched_at.tz_convert("America/New_York").strftime("%Y-%m-%d"),
                        mode=mode,
                        threshold_pct=threshold * 100.0,
                        touched_at=touched_at,
                        entry=entry,
                        direction=direction,
                        anchor_range=anchor_range,
                        target_pts=target_pts,
                        stop_pts=stop_pts,
                        result=result,
                        bars_held=bars_held,
                        pts=pts,
                    ).__dict__
                )

    trades = pd.DataFrame(records)
    if not trades.empty:
        trades["touched_at"] = pd.to_datetime(trades["touched_at"], utc=True)

    rows = []
    for threshold in thresholds:
        for mode in modes:
            subset = trades[(trades["threshold_pct"].eq(threshold * 100.0)) & (trades["mode"].eq(mode))] if not trades.empty else trades
            for year, group in subset.groupby("year"):
                rows.append(summarize(group.sort_values("touched_at"), str(year), mode, threshold))
            rows.append(summarize(subset.sort_values("touched_at"), "ALL", mode, threshold))
    summary = pd.DataFrame(rows)

    out_dir = os.path.dirname(args.out_prefix)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    trades.to_csv(f"{args.out_prefix}_trades.csv", index=False)
    summary.to_csv(f"{args.out_prefix}_summary.csv", index=False)

    print(summary.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
