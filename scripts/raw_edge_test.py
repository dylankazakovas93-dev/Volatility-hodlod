#!/usr/bin/env python3
"""Blunt raw-edge test: at every first touch of a generated level, simulate a
fixed-bracket trade in BOTH directions — "fade" (bet price reverses off the
level) and "continuation" (bet price blows through it) — with no trend
filters or other conditioning. Reports win rate and raw point expectancy for
each, by side and overall, so we can see whether either direction shows any
edge, or whether one is just a clear loser.

Example:
    python3 scripts/raw_edge_test.py \
        --ohlcv data/gc_1m/gc_continuous_1m.csv \
        --target 10 --stop 10
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from volgen.levels import GC_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
from volgen.trades import run_raw_edge_test, summarize_raw_edge


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ohlcv", required=True)
    parser.add_argument("--gvz", default="data/gvz_daily.csv")
    parser.add_argument("--tz", default="America/New_York")
    parser.add_argument("--target", type=float, default=10.0, help="target distance in points")
    parser.add_argument("--stop", type=float, default=10.0, help="stop distance in points")
    parser.add_argument("--max-bars", type=int, default=240, help="max bars to hold before timeout")
    parser.add_argument("--out", default=None, help="optional CSV path for the raw per-trade table")
    args = parser.parse_args()

    print(f"loading 1m OHLCV from {args.ohlcv} ...")
    ohlcv = load_1m_ohlcv(args.ohlcv, tz=args.tz)
    gvz = load_gvz_daily(args.gvz)

    print("generating levels ...")
    levels = generate_levels(ohlcv, gvz, params=GC_PARAMS)
    print(f"  {len(levels)} sessions produced levels")

    print(f"simulating bracket trades (target={args.target}pts, stop={args.stop}pts, max_bars={args.max_bars}) ...")
    trades = run_raw_edge_test(ohlcv, levels, target_pts=args.target, stop_pts=args.stop, max_bars=args.max_bars)
    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        trades.to_csv(args.out, index=False)
        print(f"  wrote {len(trades)} simulated trades -> {args.out}")

    print()
    print(f"=== raw edge summary (target {args.target} / stop {args.stop}, R:R = {args.target/args.stop:.2f}) ===")
    summary = summarize_raw_edge(trades)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
