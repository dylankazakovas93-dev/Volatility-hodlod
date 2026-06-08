#!/usr/bin/env python3
"""NQ level study: switch to continuation after intraday ATR expansion.

No lookahead:
- ATR uses only prior completed RTH sessions.
- The expansion trigger uses only bars from the current RTH open through the
  touch timestamp.

Modes:
- always_reversal: lower=long fade, upper=short fade.
- atr_continuation_X: reversal until current RTH session has moved at least
  X * prior ATR from the RTH open; from then on, lower=short breakdown and
  upper=long breakout for the rest of that RTH date.
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
    side: str
    direction: str
    touched_at: pd.Timestamp
    entry: float
    prior_atr: float
    expansion_ratio: float
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
        [
            daily["high"] - daily["low"],
            (daily["high"] - prev_close).abs(),
            (daily["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(atr_len, min_periods=atr_len).mean().shift(1)


def rth_opens(bars: pd.DataFrame) -> pd.Series:
    rth = bars[in_rth(bars.index)]
    dates = rth_date(rth.index)
    return rth.groupby(dates)["open"].first()


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


def bar_ranges(bars: pd.DataFrame, range_minutes: int) -> pd.Series:
    ranged = bars.resample(f"{range_minutes}min", label="left", closed="left").agg({"high": "max", "low": "min"}).dropna()
    return ranged["high"] - ranged["low"]


def previous_completed_range(ranges: pd.Series, ts: pd.Timestamp, range_minutes: int) -> float | None:
    prev_start = ts.floor(f"{range_minutes}min") - pd.Timedelta(minutes=range_minutes)
    value = ranges.get(prev_start)
    if value is None or pd.isna(value) or value <= 0:
        return None
    return float(value)


def direction_for(side: str, logic: str) -> tuple[float, str]:
    if logic == "reversal":
        return (1.0, "long_fade") if side == "lower" else (-1.0, "short_fade")
    if logic == "continuation":
        return (-1.0, "short_breakdown") if side == "lower" else (1.0, "long_breakout")
    raise ValueError(logic)


def simulate(
    bars: pd.DataFrame,
    mode: str,
    session_date,
    side: str,
    logic: str,
    touched_at: pd.Timestamp,
    level: float,
    prior_atr: float,
    expansion_ratio: float,
    range_minutes: int,
    anchor_range: float,
    tp_mult: float,
    rr: float,
    max_bars: int,
) -> Trade | None:
    future = bars.loc[touched_at:]
    if future.empty:
        return None
    sign, direction = direction_for(side, logic)
    entry = float(level)
    target_pts = anchor_range * tp_mult
    stop_pts = target_pts / rr
    target = entry + sign * target_pts
    stop = entry - sign * stop_pts
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
        return Trade(mode, session_date, date_et, date_et[:7], side, direction, touched_at, entry, prior_atr, expansion_ratio, range_minutes, anchor_range, tp_mult, rr, target_pts, stop_pts, result, i, pts)

    last_close = float(path["close"].iloc[-1])
    pts = sign * (last_close - entry)
    date_et = touched_at.tz_convert("America/New_York").strftime("%Y-%m-%d")
    return Trade(mode, session_date, date_et, date_et[:7], side, direction, touched_at, entry, prior_atr, expansion_ratio, range_minutes, anchor_range, tp_mult, rr, target_pts, stop_pts, "timeout", len(path), pts)


def profit_factor(pts: pd.Series) -> float:
    gp = float(pts[pts > 0].sum())
    gl = float(-pts[pts < 0].sum())
    if gl == 0:
        return float("inf") if gp > 0 else 0.0
    return gp / gl


def max_drawdown(pts: pd.Series) -> float:
    if pts.empty:
        return 0.0
    equity = pts.cumsum()
    return float((equity - equity.cummax()).min())


def summarize(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for mode, group in trades.groupby("mode"):
        ordered = group.sort_values("touched_at")
        rows.append(
            {
                "scope": "FULL_YEAR",
                "mode": mode,
                "month": "FULL_YEAR",
                "trade_count": len(group),
                "net_points": float(group["pts"].sum()),
                "win_rate": float(group["pts"].gt(0).mean()),
                "profit_factor": profit_factor(group["pts"]),
                "max_drawdown": max_drawdown(ordered["pts"]),
                "lower_trades": int((group["side"] == "lower").sum()),
                "upper_trades": int((group["side"] == "upper").sum()),
            }
        )
        for month, month_group in group.groupby("month"):
            ordered_month = month_group.sort_values("touched_at")
            rows.append(
                {
                    "scope": "MONTH",
                    "mode": mode,
                    "month": month,
                    "trade_count": len(month_group),
                    "net_points": float(month_group["pts"].sum()),
                    "win_rate": float(month_group["pts"].gt(0).mean()),
                    "profit_factor": profit_factor(month_group["pts"]),
                    "max_drawdown": max_drawdown(ordered_month["pts"]),
                    "lower_trades": int((month_group["side"] == "lower").sum()),
                    "upper_trades": int((month_group["side"] == "upper").sum()),
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", required=True)
    parser.add_argument("--vxn", default="data/vxn_daily.csv")
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--atr-len", type=int, default=14)
    parser.add_argument("--thresholds", default="1.0,1.25,1.5,1.75,2.0")
    parser.add_argument("--range-minutes", type=int, default=60)
    parser.add_argument("--tp-mult", type=float, default=0.5)
    parser.add_argument("--rr", type=float, default=0.75)
    parser.add_argument("--max-bars", type=int, default=24)
    parser.add_argument("--search-window-days", type=int, default=5)
    parser.add_argument("--out-prefix", default="out/nq_2025_atr_regime")
    args = parser.parse_args()

    bars = load_1m_ohlcv(args.bars)
    bars = bars[(bars.index.date >= pd.Timestamp(args.start).date()) & (bars.index.date <= pd.Timestamp(args.end).date())]
    vxn = load_gvz_daily(args.vxn)
    levels = generate_levels(bars, vxn, params=NQ_PARAMS)
    ranges = bar_ranges(bars, args.range_minutes)
    atr = completed_rth_atr(bars, args.atr_len)
    opens = rth_opens(bars)
    thresholds = parse_floats(args.thresholds)
    modes = ["always_reversal", *[f"atr_continuation_{threshold:g}" for threshold in thresholds]]

    records = []
    search_window = pd.Timedelta(days=args.search_window_days)
    for _, row in levels.iterrows():
        for side, level_col in (("lower", "lower_level"), ("upper", "upper_level")):
            level = float(row[level_col])
            window = bars.loc[row["created_at"] : row["created_at"] + search_window]
            touched_at = _first_touch(window, level)
            if touched_at is None:
                continue
            date_key = touched_at.tz_convert("America/New_York").strftime("%Y-%m-%d")
            prior_atr = atr.get(date_key)
            open_price = opens.get(date_key)
            expansion_ratio = None if open_price is None or pd.isna(prior_atr) else expansion_ratio_at_touch(bars, touched_at, float(open_price), float(prior_atr))
            if expansion_ratio is None:
                continue
            anchor_range = previous_completed_range(ranges, touched_at, args.range_minutes)
            if anchor_range is None:
                continue
            for mode in modes:
                if mode == "always_reversal":
                    logic = "reversal"
                else:
                    threshold = float(mode.rsplit("_", 1)[-1])
                    logic = "continuation" if expansion_ratio >= threshold else "reversal"
                trade = simulate(bars, mode, row["session_date"], side, logic, touched_at, level, float(prior_atr), float(expansion_ratio), args.range_minutes, anchor_range, args.tp_mult, args.rr, args.max_bars)
                if trade is not None:
                    records.append(trade.__dict__)

    trades = pd.DataFrame(records)
    summary = summarize(trades)
    out_dir = os.path.dirname(args.out_prefix)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    trades.to_csv(f"{args.out_prefix}_trades.csv", index=False)
    summary.to_csv(f"{args.out_prefix}_summary.csv", index=False)

    full = summary[summary["scope"].eq("FULL_YEAR")].sort_values("net_points", ascending=False)
    print("=== FULL YEAR ===")
    print(full.to_string(index=False))
    print("\n=== MONTHLY ===")
    monthly = summary[summary["scope"].eq("MONTH")].sort_values(["mode", "month"])
    print(monthly.to_string(index=False))


if __name__ == "__main__":
    main()
