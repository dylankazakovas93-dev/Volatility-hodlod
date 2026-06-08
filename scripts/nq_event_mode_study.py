#!/usr/bin/env python3
"""NQ level event-day reversal vs continuation study.

Modes:
- always_reversal: lower=long fade, upper=short fade on every day.
- skip_events: reversal on non-event days only.
- event_continuation: reversal on non-event days; event days flip to continuation.
- event_only_reversal: reversal trades only on event days.
- event_only_continuation: continuation trades only on event days.

Continuation is the mechanical opposite of the fade:
- lower level touch = short breakdown
- upper level touch = long breakout

Entry fills at the level price on first touch. Same-bar TP/SL is not inspected
because 5m OHLC cannot tell whether the post-touch path happened before or after
the touch inside that bar.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from volgen.levels import NQ_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.reactions import _first_touch


@dataclass(frozen=True)
class Trade:
    mode: str
    session_date: object
    date_et: str
    month: str
    event_types: str
    side: str
    direction: str
    touched_at: pd.Timestamp
    entry: float
    range_minutes: int
    anchor_range: float
    tp_mult: float
    rr: float
    target_pts: float
    stop_pts: float
    result: str
    bars_held: int
    pts: float


def parse_floats(raw: str) -> list[float]:
    return [float(part) for part in raw.split(",") if part.strip()]


def bar_ranges(bars: pd.DataFrame, range_minutes: int) -> pd.Series:
    ranged = bars.resample(f"{range_minutes}min", label="left", closed="left").agg({"high": "max", "low": "min"}).dropna()
    return ranged["high"] - ranged["low"]


def previous_completed_range(ranges: pd.Series, ts: pd.Timestamp, range_minutes: int) -> float | None:
    prev_start = ts.floor(f"{range_minutes}min") - pd.Timedelta(minutes=range_minutes)
    value = ranges.get(prev_start)
    if value is None or pd.isna(value) or value <= 0:
        return None
    return float(value)


def session_cutoff(
    touched_at: pd.Timestamp,
    cutoff_time: str,
    resume_time: str | None,
) -> pd.Timestamp | None:
    """Return the ET session cutoff for a touch, or None when entries are paused."""
    touched_et = touched_at.tz_convert("America/New_York")
    touch_date = touched_et.strftime("%Y-%m-%d")
    same_day_cutoff = pd.Timestamp(f"{touch_date} {cutoff_time}", tz="America/New_York")

    if resume_time is None:
        if touched_et >= same_day_cutoff:
            return None
        return same_day_cutoff.tz_convert(touched_at.tz)

    same_day_resume = pd.Timestamp(f"{touch_date} {resume_time}", tz="America/New_York")
    if touched_et < same_day_cutoff:
        return same_day_cutoff.tz_convert(touched_at.tz)
    if touched_et >= same_day_resume:
        next_day = touched_et.normalize() + pd.Timedelta(days=1)
        next_cutoff = pd.Timestamp(f"{next_day.strftime('%Y-%m-%d')} {cutoff_time}", tz="America/New_York")
        return next_cutoff.tz_convert(touched_at.tz)
    return None


def load_events(path: str) -> dict[str, set[str]]:
    df = pd.read_csv(path)
    out: dict[str, set[str]] = {}
    for _, row in df.iterrows():
        out.setdefault(str(row["date"]), set()).add(str(row["event_type"]))
    return out


def direction_for(side: str, trade_logic: str) -> tuple[float, str]:
    if trade_logic == "reversal":
        return (1.0, "long_fade") if side == "lower" else (-1.0, "short_fade")
    if trade_logic == "continuation":
        return (-1.0, "short_breakdown") if side == "lower" else (1.0, "long_breakout")
    raise ValueError(f"unknown trade_logic {trade_logic}")


def simulate(
    bars: pd.DataFrame,
    mode: str,
    session_date,
    event_types: str,
    side: str,
    trade_logic: str,
    touched_at: pd.Timestamp,
    level: float,
    range_minutes: int,
    anchor_range: float,
    tp_mult: float,
    rr: float,
    max_bars: int,
    exit_cutoff_time: str | None,
    resume_time: str | None,
) -> Trade | None:
    future = bars.loc[touched_at:]
    if future.empty:
        return None
    sign, direction = direction_for(side, trade_logic)
    entry = float(level)
    target_pts = anchor_range * tp_mult
    stop_pts = target_pts / rr
    target = entry + sign * target_pts
    stop = entry - sign * stop_pts
    if exit_cutoff_time:
        cutoff = session_cutoff(touched_at, exit_cutoff_time, resume_time)
        if cutoff is None:
            return None
        path = future.loc[:cutoff].iloc[1:]
    else:
        path = future.iloc[1 : max_bars + 1]
    if path.empty:
        return None

    for i, (_, bar) in enumerate(path.iterrows(), start=1):
        hi = float(bar["high"])
        lo = float(bar["low"])
        if sign > 0:
            hit_target = hi >= target
            hit_stop = lo <= stop
        else:
            hit_target = lo <= target
            hit_stop = hi >= stop
        if hit_target and hit_stop:
            result, pts = "stop", -stop_pts
        elif hit_stop:
            result, pts = "stop", -stop_pts
        elif hit_target:
            result, pts = "target", target_pts
        else:
            continue
        date_et = touched_at.tz_convert("America/New_York").strftime("%Y-%m-%d")
        return Trade(mode, session_date, date_et, date_et[:7], event_types, side, direction, touched_at, entry, range_minutes, anchor_range, tp_mult, rr, target_pts, stop_pts, result, i, pts)

    last_close = float(path["close"].iloc[-1])
    pts = sign * (last_close - entry)
    date_et = touched_at.tz_convert("America/New_York").strftime("%Y-%m-%d")
    return Trade(mode, session_date, date_et, date_et[:7], event_types, side, direction, touched_at, entry, range_minutes, anchor_range, tp_mult, rr, target_pts, stop_pts, "timeout", len(path), pts)


def logic_for_mode(mode: str, event_type_set: set[str]) -> str | None:
    is_event = bool(event_type_set)
    if mode == "always_reversal":
        return "reversal"
    if mode == "skip_events":
        return None if is_event else "reversal"
    if mode == "event_continuation":
        return "continuation" if is_event else "reversal"
    if mode == "event_only_reversal":
        return "reversal" if is_event else None
    if mode == "event_only_continuation":
        return "continuation" if is_event else None
    if mode.startswith("continue_"):
        event_type = mode.removeprefix("continue_")
        return "continuation" if event_type in event_type_set else "reversal"
    if mode.startswith("skip_"):
        event_type = mode.removeprefix("skip_")
        return None if event_type in event_type_set else "reversal"
    raise ValueError(f"unknown mode {mode}")


def profit_factor(pts: pd.Series) -> float:
    gross_profit = float(pts[pts > 0].sum())
    gross_loss = float(-pts[pts < 0].sum())
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def summarize_group(group: pd.DataFrame) -> dict[str, object]:
    return {
        "trade_count": len(group),
        "net_points": float(group["pts"].sum()) if not group.empty else 0.0,
        "win_rate": float(group["pts"].gt(0).mean()) if not group.empty else float("nan"),
        "profit_factor": profit_factor(group["pts"]) if not group.empty else float("nan"),
        "lower_trades": int((group["side"] == "lower").sum()) if not group.empty else 0,
        "upper_trades": int((group["side"] == "upper").sum()) if not group.empty else 0,
    }


def make_summaries(trades: pd.DataFrame, config: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows = []
    for mode, group in trades.groupby("mode"):
        rows.append({"config": config, "scope": "FULL_YEAR", "mode": mode, "month": "FULL_YEAR", **summarize_group(group)})
        for month, month_group in group.groupby("month"):
            rows.append({"config": config, "scope": "MONTH", "mode": mode, "month": month, **summarize_group(month_group)})
    strategy = pd.DataFrame(rows)

    bucket_rows = []
    event_trades = trades[trades["event_types"].ne("")]
    for _, row in event_trades.iterrows():
        for event_type in str(row["event_types"]).split("|"):
            bucket_rows.append({**row.to_dict(), "event_type": event_type})
    exploded = pd.DataFrame(bucket_rows)
    bucket_summary = pd.DataFrame()
    date_summary = pd.DataFrame()
    if not exploded.empty:
        bucket_rows_out = []
        for (mode, event_type), group in exploded.groupby(["mode", "event_type"]):
            bucket_rows_out.append({"config": config, "mode": mode, "event_type": event_type, **summarize_group(group)})
        bucket_summary = pd.DataFrame(bucket_rows_out)

        date_rows_out = []
        for (mode, date_et, event_type), group in exploded.groupby(["mode", "date_et", "event_type"]):
            date_rows_out.append({"config": config, "mode": mode, "date_et": date_et, "event_type": event_type, **summarize_group(group)})
        date_summary = pd.DataFrame(date_rows_out).sort_values(["mode", "date_et", "event_type"])
    return strategy, bucket_summary, date_summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", required=True)
    parser.add_argument("--vxn", default="data/vxn_daily.csv")
    parser.add_argument("--events", default="data/nq_2025_event_days.csv")
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--range-minutes", type=int, default=60)
    parser.add_argument("--tp-mult", type=float, default=0.5)
    parser.add_argument("--rr", type=float, default=0.75)
    parser.add_argument("--max-bars", type=int, default=24)
    parser.add_argument("--exit-cutoff-time", default=None, help="Optional ET clock-time timeout, e.g. 15:00. If set, ignores --max-bars and exits at this time on the touch date.")
    parser.add_argument("--resume-time", default=None, help="Optional ET clock-time when entries resume after the cutoff, e.g. 19:00. Touches after resume exit at the next day's cutoff.")
    parser.add_argument("--search-window-days", type=int, default=5)
    parser.add_argument("--out-prefix", default="out/nq_2025_event_study")
    args = parser.parse_args()

    bars = load_1m_ohlcv(args.bars)
    bars = bars[(bars.index.date >= pd.Timestamp(args.start).date()) & (bars.index.date <= pd.Timestamp(args.end).date())]
    vxn = load_gvz_daily(args.vxn)
    levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges = bar_ranges(bars, args.range_minutes)
    events = load_events(args.events)

    event_type_names = sorted({event_type for event_set in events.values() for event_type in event_set})
    modes = [
        "always_reversal",
        "skip_events",
        "event_continuation",
        "event_only_reversal",
        "event_only_continuation",
        *[f"continue_{event_type}" for event_type in event_type_names],
        *[f"skip_{event_type}" for event_type in event_type_names],
    ]
    records = []
    search_window = pd.Timedelta(days=args.search_window_days)
    for _, level_row in levels.iterrows():
        session_date = level_row["session_date"]
        for side, level_col in (("lower", "lower_level"), ("upper", "upper_level")):
            level = float(level_row[level_col])
            window = bars.loc[level_row["created_at"] : level_row["created_at"] + search_window]
            touched_at = _first_touch(window, level)
            if touched_at is None:
                continue
            touch_key = touched_at.tz_convert("America/New_York").strftime("%Y-%m-%d")
            event_type_set = events.get(touch_key, set())
            event_types = "|".join(sorted(event_type_set))
            anchor_range = previous_completed_range(ranges, touched_at, args.range_minutes)
            if anchor_range is None:
                continue
            for mode in modes:
                trade_logic = logic_for_mode(mode, event_type_set)
                if trade_logic is None:
                    continue
                trade = simulate(bars, mode, session_date, event_types, side, trade_logic, touched_at, level, args.range_minutes, anchor_range, args.tp_mult, args.rr, args.max_bars, args.exit_cutoff_time, args.resume_time)
                if trade is not None:
                    records.append(trade.__dict__)

    trades = pd.DataFrame(records)
    config = f"TP_{args.tp_mult:g}x_prev_{args.range_minutes}m_RR_{args.rr:g}"
    strategy, bucket, date_summary = make_summaries(trades, config)

    out_dir = os.path.dirname(args.out_prefix)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    trades.to_csv(f"{args.out_prefix}_trades.csv", index=False)
    strategy.to_csv(f"{args.out_prefix}_strategy_summary.csv", index=False)
    bucket.to_csv(f"{args.out_prefix}_bucket_summary.csv", index=False)
    date_summary.to_csv(f"{args.out_prefix}_date_summary.csv", index=False)

    print("=== STRATEGY FULL YEAR ===")
    full = strategy[strategy["scope"].eq("FULL_YEAR")].copy()
    print(full.to_string(index=False))
    print("\n=== EVENT BUCKETS ===")
    print(bucket.to_string(index=False) if not bucket.empty else "No event trades")
    print("\n=== WORST EVENT DATES ===")
    if not date_summary.empty:
        print(date_summary.sort_values("net_points").head(20).to_string(index=False))


if __name__ == "__main__":
    main()
