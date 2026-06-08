#!/usr/bin/env python3
"""Smoke-test volgen against synthetic data so we know the pipeline runs
before pointing it at the real (large, untracked) GC 1-minute file."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from volgen.levels import GC_PARAMS, generate_levels, load_gvz_daily
from volgen.reactions import evaluate_levels, summarize


def make_synthetic_1m(n_days: int = 30, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames = []
    price = 2000.0
    for d in range(n_days):
        day = pd.Timestamp("2024-01-02", tz="America/New_York") + pd.Timedelta(days=d * 7 // 5)
        if day.weekday() >= 5:
            continue
        idx = pd.date_range(day + pd.Timedelta(hours=9, minutes=30), periods=390, freq="1min", tz="America/New_York")
        steps = rng.normal(0, 0.6, size=len(idx))
        closes = price + np.cumsum(steps)
        opens = np.r_[closes[0], closes[:-1]]
        highs = np.maximum(opens, closes) + rng.uniform(0, 0.8, size=len(idx))
        lows = np.minimum(opens, closes) - rng.uniform(0, 0.8, size=len(idx))
        frames.append(pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes}, index=idx))
        price = closes[-1]
    df = pd.concat(frames)
    df.index.name = "time"
    return df


def main() -> None:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    gvz = load_gvz_daily(os.path.join(repo_root, "data", "gvz_daily.csv"))
    ohlcv = make_synthetic_1m()

    levels = generate_levels(ohlcv, gvz, params=GC_PARAMS)
    assert not levels.empty, "expected at least one session of levels"
    print(f"generated {len(levels)} sessions of levels from {len(ohlcv)} synthetic 1m bars")
    print(levels.head(3).to_string(index=False))

    results = evaluate_levels(ohlcv, levels, horizons_minutes=(15, 60))
    print()
    print(summarize(results, horizons_minutes=(15, 60)).to_string(index=False))
    print()
    print("OK — pipeline runs end to end")


if __name__ == "__main__":
    main()
