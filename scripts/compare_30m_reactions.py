#!/usr/bin/env python3
"""Compare 30-minute fade-direction reactions after VDL level touches."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from volgen.levels import GC_PARAMS, NQ_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.reactions import _first_touch


PARAMS = {"GC": GC_PARAMS, "NQ": NQ_PARAMS}


@dataclass(frozen=True)
class TouchReaction:
    market: str
    session_date: object
    side: str
    level: float
    touched_at: pd.Timestamp
    mfe: float
    mae: float
    net_30m: float
    fade_win_x: bool


def measure_one(
    bars: pd.DataFrame,
    market: str,
    session_date,
    side: str,
    level: float,
    created_at: pd.Timestamp,
    threshold: float,
    horizon_minutes: int,
    search_window: pd.Timedelta,
) -> TouchReaction | None:
    window = bars.loc[created_at : created_at + search_window]
    touched_at = _first_touch(window, level)
    if touched_at is None:
        return None
    future = bars.loc[touched_at : touched_at + pd.Timedelta(minutes=horizon_minutes)]
    if future.empty:
        return None
    entry = float(future["close"].iloc[0])
    close_30 = float(future["close"].iloc[-1])
    if side == "upper":
        # Fade direction is down.
        mfe = entry - float(future["low"].min())
        mae = float(future["high"].max()) - entry
        net = entry - close_30
        fade_hit = future["low"] <= entry - threshold
        adverse_hit = future["high"] >= entry + threshold
    else:
        # Fade direction is up.
        mfe = float(future["high"].max()) - entry
        mae = entry - float(future["low"].min())
        net = close_30 - entry
        fade_hit = future["high"] >= entry + threshold
        adverse_hit = future["low"] <= entry - threshold
    fade_win = False
    for i in range(len(future)):
        hit_fade = bool(fade_hit.iloc[i])
        hit_adverse = bool(adverse_hit.iloc[i])
        if hit_fade and hit_adverse:
            fade_win = False
            break
        if hit_adverse:
            fade_win = False
            break
        if hit_fade:
            fade_win = True
            break
    return TouchReaction(market, session_date, side, level, touched_at, mfe, mae, net, fade_win)


def evaluate(
    market: str,
    bars_path: str,
    vol_path: str,
    start: str,
    end: str,
    threshold: float,
    horizon_minutes: int,
) -> pd.DataFrame:
    bars = load_1m_ohlcv(bars_path)
    if start:
        bars = bars[bars.index.date >= pd.Timestamp(start).date()]
    if end:
        bars = bars[bars.index.date <= pd.Timestamp(end).date()]
    vol = load_gvz_daily(vol_path)
    levels = generate_levels(bars, vol, params=PARAMS[market])
    records = []
    for _, row in levels.iterrows():
        for side, col in (("upper", "upper_level"), ("lower", "lower_level")):
            rec = measure_one(
                bars,
                market,
                row["session_date"],
                side,
                float(row[col]),
                row["created_at"],
                threshold,
                horizon_minutes,
                pd.Timedelta(days=5),
            )
            if rec is not None:
                records.append(rec.__dict__)
    return pd.DataFrame(records)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, group in df.groupby(["market", "side"]):
        market, side = keys
        rows.append(
            {
                "market": market,
                "side": side,
                "touch_count": len(group),
                "median_mfe": group["mfe"].median(),
                "median_mae": group["mae"].median(),
                "median_net_30m": group["net_30m"].median(),
                "mean_net_30m": group["net_30m"].mean(),
                "win_rate_x": group["fade_win_x"].mean(),
            }
        )
    for market, group in df.groupby("market"):
        rows.append(
            {
                "market": market,
                "side": "ALL",
                "touch_count": len(group),
                "median_mfe": group["mfe"].median(),
                "median_mae": group["mae"].median(),
                "median_net_30m": group["net_30m"].median(),
                "mean_net_30m": group["net_30m"].mean(),
                "win_rate_x": group["fade_win_x"].mean(),
            }
        )
    return pd.DataFrame(rows).sort_values(["market", "side"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nq-bars", required=True)
    parser.add_argument("--nq-vol", default="data/vxn_daily.csv")
    parser.add_argument("--gc-bars", required=True)
    parser.add_argument("--gc-vol", default="data/gvz_daily.csv")
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--threshold", type=float, default=10.0)
    parser.add_argument("--horizon-minutes", type=int, default=30)
    parser.add_argument("--out-touches", default=None)
    parser.add_argument("--out-summary", default=None)
    args = parser.parse_args()

    nq = evaluate("NQ", args.nq_bars, args.nq_vol, args.start, args.end, args.threshold, args.horizon_minutes)
    gc = evaluate("GC", args.gc_bars, args.gc_vol, args.start, args.end, args.threshold, args.horizon_minutes)
    touches = pd.concat([nq, gc], ignore_index=True)
    summary = summarize(touches)
    if args.out_touches:
        os.makedirs(os.path.dirname(args.out_touches) or ".", exist_ok=True)
        touches.to_csv(args.out_touches, index=False)
    if args.out_summary:
        os.makedirs(os.path.dirname(args.out_summary) or ".", exist_ok=True)
        summary.to_csv(args.out_summary, index=False)
    display = summary.copy()
    for col in ("median_mfe", "median_mae", "median_net_30m", "mean_net_30m", "win_rate_x"):
        display[col] = display[col].map(lambda x: f"{x:.3f}")
    print(display.to_string(index=False))


if __name__ == "__main__":
    main()
