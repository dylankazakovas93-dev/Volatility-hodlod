#!/usr/bin/env python3
"""Slice per-level reaction results (from backtest_levels.py --out-results)
by year and by side (upper/lower) — the aggregate touch-rate/reaction stats
can hide whether the effect is concentrated in a particular regime (e.g. the
user's observation that 2026 produced unusually large reactions on GC).

Usage:
    python3 scripts/analyze_by_year_side.py --results out/gc_level_reactions.csv
"""
import argparse

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default="out/gc_level_reactions.csv")
    parser.add_argument("--horizons", default="15,60,120")
    args = parser.parse_args()
    horizons = [int(h) for h in args.horizons.split(",")]

    res = pd.read_csv(args.results)
    res["created_at"] = pd.to_datetime(res["created_at"], utc=True, format="mixed")
    res["touched_at"] = pd.to_datetime(res["touched_at"], utc=True, format="mixed")
    res = res.dropna(subset=["touched_at"])
    res["year"] = res["created_at"].dt.year

    for h in horizons:
        rcol, ccol, ncol = f"reaction_{h}m", f"continuation_{h}m", f"net_bias_{h}m"
        sub = res.dropna(subset=[rcol])
        print(f"\n=== horizon {h}m  (net_bias = reaction - continuation; >0 favors reversal) ===")
        g = sub.groupby(["year", "side"]).agg(
            n=(ncol, "size"),
            pct_reaction_wins=(ncol, lambda s: (s > 0).mean()),
            median_net_bias=(ncol, "median"),
            mean_net_bias=(ncol, "mean"),
            median_reaction_pts=(rcol, "median"),
            median_continuation_pts=(ccol, "median"),
        ).round(3)
        print(g.to_string())


if __name__ == "__main__":
    main()
