#!/usr/bin/env python3
"""NQ first-touch reversion test with previous completed range exits.

Entry:
- first touch of each generated NQ level
- lower level = long fade
- upper level = short fade

Exit:
- TP = previous completed range bar high-low * tp_mult
- SL = TP / rr

No costs or slippage. Same-bar TP/SL ties resolve to stop.
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
    session_date: object
    month: str
    side: str
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
    rule = f"{range_minutes}min"
    ranged = bars.resample(rule, label="left", closed="left").agg({"high": "max", "low": "min"}).dropna()
    return ranged["high"] - ranged["low"]


def previous_completed_range(ranges: pd.Series, ts: pd.Timestamp, range_minutes: int) -> float | None:
    rule = f"{range_minutes}min"
    prev_start = ts.floor(rule) - pd.Timedelta(minutes=range_minutes)
    value = ranges.get(prev_start)
    if value is None or pd.isna(value) or value <= 0:
        return None
    return float(value)


def side_sign(side: str) -> float:
    return 1.0 if side == "lower" else -1.0


def simulate(
    bars: pd.DataFrame,
    session_date,
    side: str,
    touched_at: pd.Timestamp,
    level: float,
    range_minutes: int,
    anchor_range: float,
    tp_mult: float,
    rr: float,
    max_bars: int,
) -> Trade | None:
    future = bars.loc[touched_at:]
    if future.empty:
        return None
    sign = side_sign(side)
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
            return Trade(session_date, str(session_date)[:7], side, touched_at, entry, range_minutes, anchor_range, tp_mult, rr, target_pts, stop_pts, "stop", i, -stop_pts)
        if hit_stop:
            return Trade(session_date, str(session_date)[:7], side, touched_at, entry, range_minutes, anchor_range, tp_mult, rr, target_pts, stop_pts, "stop", i, -stop_pts)
        if hit_target:
            return Trade(session_date, str(session_date)[:7], side, touched_at, entry, range_minutes, anchor_range, tp_mult, rr, target_pts, stop_pts, "target", i, target_pts)

    last_close = float(path["close"].iloc[-1])
    pts = sign * (last_close - entry)
    return Trade(session_date, str(session_date)[:7], side, touched_at, entry, range_minutes, anchor_range, tp_mult, rr, target_pts, stop_pts, "timeout", len(path), pts)


def run_config(
    bars: pd.DataFrame,
    levels: pd.DataFrame,
    ranges: pd.Series,
    range_minutes: int,
    tp_mult: float,
    rr: float,
    max_bars: int,
    search_window_days: int,
) -> pd.DataFrame:
    records = []
    search_window = pd.Timedelta(days=search_window_days)
    for _, row in levels.iterrows():
        for side, level_col in (("lower", "lower_level"), ("upper", "upper_level")):
            level = float(row[level_col])
            window = bars.loc[row["created_at"] : row["created_at"] + search_window]
            touched_at = _first_touch(window, level)
            if touched_at is None:
                continue
            anchor_range = previous_completed_range(ranges, touched_at, range_minutes)
            if anchor_range is None:
                continue
            trade = simulate(bars, row["session_date"], side, touched_at, level, range_minutes, anchor_range, tp_mult, rr, max_bars)
            if trade is None:
                continue
            records.append(trade.__dict__)
    return pd.DataFrame(records)


def profit_factor(pts: pd.Series) -> float:
    gross_profit = float(pts[pts > 0].sum())
    gross_loss = float(-pts[pts < 0].sum())
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def summarize(trades: pd.DataFrame, range_minutes: int, tp_mult: float, rr: float, label: str) -> list[dict[str, object]]:
    rows = []
    groups = [("FULL_YEAR", trades), *[(month, group) for month, group in trades.groupby("month")]]
    for month, group in groups:
        rows.append(
            {
                "config": label,
                "range_minutes": range_minutes,
                "tp_mult": tp_mult,
                "rr": rr,
                "month": month,
                "trade_count": len(group),
                "low_confidence": len(group) < 5,
                "net_points": float(group["pts"].sum()) if not group.empty else 0.0,
                "win_rate": float(group["pts"].gt(0).mean()) if not group.empty else float("nan"),
                "profit_factor": profit_factor(group["pts"]) if not group.empty else float("nan"),
                "lower_trades": int((group["side"] == "lower").sum()) if not group.empty else 0,
                "upper_trades": int((group["side"] == "upper").sum()) if not group.empty else 0,
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", required=True)
    parser.add_argument("--vxn", default="data/vxn_daily.csv")
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--tp-mults", default="1.0,0.5")
    parser.add_argument("--rr", default="1,2,3,4")
    parser.add_argument("--range-minutes", default="60", help="Comma-separated completed range anchors, e.g. 60,240")
    parser.add_argument("--max-bars", type=int, default=24, help="Bars in the input timeframe; 24 = 24 minutes on 1m data or 120 minutes on 5m data.")
    parser.add_argument("--search-window-days", type=int, default=5)
    parser.add_argument("--out-trades", default=None)
    parser.add_argument("--out-summary", default=None)
    args = parser.parse_args()

    bars = load_1m_ohlcv(args.bars)
    bars = bars[(bars.index.date >= pd.Timestamp(args.start).date()) & (bars.index.date <= pd.Timestamp(args.end).date())]
    vxn = load_gvz_daily(args.vxn)
    levels = generate_levels(bars, vxn, params=NQ_PARAMS)

    all_trades = []
    summary_rows = []
    for range_minutes in [int(value) for value in parse_floats(args.range_minutes)]:
        ranges = bar_ranges(bars, range_minutes)
        for tp_mult in parse_floats(args.tp_mults):
            for rr in parse_floats(args.rr):
                trades = run_config(bars, levels, ranges, range_minutes, tp_mult, rr, args.max_bars, args.search_window_days)
                range_label = f"{range_minutes // 60}h" if range_minutes % 60 == 0 else f"{range_minutes}m"
                label = f"TP_{tp_mult:g}x_prev_{range_label}_RR_{rr:g}"
                if not trades.empty:
                    trades["config"] = label
                    all_trades.append(trades)
                summary_rows.extend(summarize(trades, range_minutes, tp_mult, rr, label))

    summary = pd.DataFrame(summary_rows).sort_values(["config", "month"])
    trades_out = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    if args.out_summary:
        os.makedirs(os.path.dirname(args.out_summary) or ".", exist_ok=True)
        summary.to_csv(args.out_summary, index=False)
    if args.out_trades and not trades_out.empty:
        os.makedirs(os.path.dirname(args.out_trades) or ".", exist_ok=True)
        trades_out.to_csv(args.out_trades, index=False)

    full = summary[summary["month"] == "FULL_YEAR"].copy()
    for col in ("net_points", "win_rate", "profit_factor"):
        full[col] = full[col].map(lambda x: f"{x:.3f}")
    print("=== FULL YEAR ===")
    print(full.to_string(index=False))
    print()
    print("=== MONTHLY ===")
    monthly = summary[summary["month"] != "FULL_YEAR"].copy()
    for col in ("net_points", "win_rate", "profit_factor"):
        monthly[col] = monthly[col].map(lambda x: f"{x:.3f}")
    print(monthly.to_string(index=False))


if __name__ == "__main__":
    main()
