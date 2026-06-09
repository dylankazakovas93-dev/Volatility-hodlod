#!/usr/bin/env python3
"""Verify Codex's ATR-flip rule: on lower-level touches, normally fade long,
but if NQ is already down >= threshold x prior-14-session RTH ATR from RTH open
at the moment of touch, flip to short continuation instead.

Upper-level touches: always reversal (short), unchanged.
Risk control: stop after first losing trade of the day.

This reproduces Codex's reported numbers and sweeps nearby ATR thresholds
(0.8x–2.0x) so we can check whether 1.3x is smooth or a cliff edge.
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


def downside_expansion_at_touch(bars: pd.DataFrame, touched_at: pd.Timestamp, open_price: float, prior_atr: float) -> float | None:
    """Max downside move from RTH open to touched_at, normalized by prior ATR."""
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


def simulate(bars, sign, touched_at, level, anchor_range, tp_mult, rr, cutoff_time, resume_time):
    future = bars.loc[touched_at:]
    if future.empty:
        return None
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
            ht, hs = hi >= target, lo <= stop
        else:
            ht, hs = lo <= target, hi >= stop
        if hs:
            return -stop_pts
        if ht:
            return target_pts
    return sign * (float(path["close"].iloc[-1]) - entry)


def apply_stop_after_loss(records: list[dict]) -> list[dict]:
    df = pd.DataFrame(records).sort_values("touched_at")
    keep = []
    for _, day_df in df.groupby("date_et"):
        for _, row in day_df.iterrows():
            keep.append(row)
            if row["pts"] < 0:
                break
    return keep


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


def summarize(kept: list[dict], label: str) -> None:
    df = pd.DataFrame(kept)
    if df.empty:
        print(f"{label}: no trades")
        return
    for yr in sorted(df["year"].unique()):
        sub = df[df["year"] == yr]["pts"]
        print(f"  {yr}: n={len(sub):3d}  net={sub.sum():9.2f}  PF={profit_factor(sub):.3f}  maxDD={max_drawdown(sub):.2f}")
    all_pts = df["pts"]
    print(f"  ALL : n={len(all_pts):3d}  net={all_pts.sum():9.2f}  PF={profit_factor(all_pts):.3f}  maxDD={max_drawdown(all_pts):.2f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", required=True)
    parser.add_argument("--vxn", default="data/vxn_daily_2020_2026.csv")
    parser.add_argument("--start", default="2023-01-01")
    parser.add_argument("--end", default="2026-06-07")
    parser.add_argument("--atr-thresholds", default="0.8,1.0,1.1,1.2,1.3,1.4,1.5,1.7,2.0")
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
    thresholds = [float(x) for x in args.atr_thresholds.split(",")]

    # Build all raw trades (both sides, both logics, with expansion computed)
    raw = []
    search_window = pd.Timedelta(days=5)
    for _, row in levels.iterrows():
        for side, col in (("lower", "lower_level"), ("upper", "upper_level")):
            level = float(row[col])
            window = bars.loc[row["created_at"]: row["created_at"] + search_window]
            touched_at = _first_touch(window, level)
            if touched_at is None:
                continue
            anchor = previous_completed_range(ranges, touched_at, args.range_minutes)
            if anchor is None:
                continue
            date_key = touched_at.tz_convert("America/New_York").strftime("%Y-%m-%d")
            prior_atr = atr.get(date_key)
            open_price = opens.get(date_key)
            expansion = None
            if side == "lower" and open_price is not None and prior_atr is not None and not pd.isna(prior_atr):
                expansion = downside_expansion_at_touch(bars, touched_at, float(open_price), float(prior_atr))

            # reversal sign: lower=+1 (long), upper=-1 (short)
            rev_sign = 1.0 if side == "lower" else -1.0
            rev_pts = simulate(bars, rev_sign, touched_at, level, anchor, args.tp_mult, args.rr, args.cutoff_time, args.resume_time)
            cont_pts = simulate(bars, -rev_sign, touched_at, level, anchor, args.tp_mult, args.rr, args.cutoff_time, args.resume_time) if side == "lower" else None
            if rev_pts is None:
                continue
            raw.append({
                "date_et": date_key,
                "year": touched_at.tz_convert("America/New_York").year,
                "side": side,
                "touched_at": touched_at,
                "expansion": expansion,
                "rev_pts": rev_pts,
                "cont_pts": cont_pts,
            })

    print(f"Total raw touches: {len(raw)}")

    # Baseline: always reversal + stop_after_loss
    base_records = [{"date_et": r["date_et"], "year": r["year"], "touched_at": r["touched_at"], "pts": r["rev_pts"]} for r in raw]
    print("\n=== BASELINE: always reversal + stop_after_loss ===")
    summarize(apply_stop_after_loss(base_records), "baseline")

    # ATR flip sweep
    print(f"\n=== ATR FLIP SWEEP (lower flip to short if down >= threshold x ATR) + stop_after_loss ===")
    for threshold in thresholds:
        records = []
        for r in raw:
            if r["side"] == "upper":
                pts = r["rev_pts"]
            elif r["expansion"] is not None and r["expansion"] >= threshold and r["cont_pts"] is not None:
                pts = r["cont_pts"]
            else:
                pts = r["rev_pts"]
            records.append({"date_et": r["date_et"], "year": r["year"], "touched_at": r["touched_at"], "pts": pts})
        kept = apply_stop_after_loss(records)
        print(f"\nATR threshold {threshold:.1f}x:")
        summarize(kept, f"atr_{threshold}")


if __name__ == "__main__":
    main()
