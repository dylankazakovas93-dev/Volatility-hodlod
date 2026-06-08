#!/usr/bin/env python3
"""Replay the mu +/- k*sigma/sqrt(dev) level generator over historical GC
1-minute bars and measure whether price reacts at the generated levels.

Example:
    python3 scripts/backtest_levels.py \
        --ohlcv data/gc_1m/GC_2023_2026_1m.csv \
        --gvz data/gvz_daily.csv \
        --out-levels out/gc_levels.csv \
        --out-results out/gc_level_reactions.csv
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from volgen.levels import GC_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.reactions import evaluate_levels, summarize


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ohlcv", required=True, help="path to 1-minute GC OHLCV CSV")
    parser.add_argument("--gvz", default="data/gvz_daily.csv", help="path to GVZ daily OHLC CSV")
    parser.add_argument("--tz", default="America/New_York", help="exchange timezone of the OHLCV timestamps")
    parser.add_argument("--rth-start", default="09:30")
    parser.add_argument("--rth-end", default="16:00")
    parser.add_argument(
        "--horizons",
        default="5,15,30,60,120",
        help="comma-separated minute horizons to measure reactions over",
    )
    parser.add_argument(
        "--reaction-threshold",
        type=float,
        default=0.0,
        help="minimum points-of-reversal-through-the-level to count as a 'reaction' "
        "(0 = any move back through the level counts)",
    )
    parser.add_argument("--out-levels", default=None, help="optional CSV path to dump generated levels")
    parser.add_argument("--out-results", default=None, help="optional CSV path to dump per-level reaction stats")
    args = parser.parse_args()

    horizons = tuple(int(h) for h in args.horizons.split(","))

    print(f"loading 1m OHLCV from {args.ohlcv} ...")
    ohlcv = load_1m_ohlcv(args.ohlcv, tz=args.tz)
    print(f"  {len(ohlcv):,} bars, {ohlcv.index[0]} -> {ohlcv.index[-1]}")

    print(f"loading GVZ daily closes from {args.gvz} ...")
    gvz = load_gvz_daily(args.gvz)
    print(f"  {len(gvz):,} sessions, {gvz.index[0].date()} -> {gvz.index[-1].date()}")

    print("generating levels ...")
    levels = generate_levels(ohlcv, gvz, params=GC_PARAMS, rth_start=args.rth_start, rth_end=args.rth_end)
    print(f"  {len(levels)} sessions produced levels")
    if args.out_levels:
        os.makedirs(os.path.dirname(args.out_levels) or ".", exist_ok=True)
        levels.to_csv(args.out_levels, index=False)
        print(f"  wrote levels -> {args.out_levels}")

    print("measuring reactions at touched levels ...")
    results = evaluate_levels(ohlcv, levels, horizons_minutes=horizons, reaction_threshold=args.reaction_threshold)
    if args.out_results:
        os.makedirs(os.path.dirname(args.out_results) or ".", exist_ok=True)
        results.to_csv(args.out_results, index=False)
        print(f"  wrote per-level results -> {args.out_results}")

    print()
    print("=== summary ===")
    summary = summarize(results, horizons_minutes=horizons)
    for _, row in summary.iterrows():
        val = row["value"]
        if isinstance(val, float):
            print(f"  {row['metric']:<48} {val:.4f}")
        else:
            print(f"  {row['metric']:<48} {val}")


if __name__ == "__main__":
    main()
