#!/usr/bin/env python3
"""Resample an OHLCV CSV to a larger bar interval."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--out", dest="out_path", required=True, type=Path)
    parser.add_argument("--freq", default="5min")
    parser.add_argument("--tz", default="America/New_York")
    args = parser.parse_args()

    df = pd.read_csv(args.in_path)
    ts_col = "timestamp" if "timestamp" in df.columns else "ts_event"
    idx = pd.to_datetime(df[ts_col], utc=False)
    if idx.dt.tz is None:
        idx = idx.dt.tz_localize(args.tz)
    else:
        idx = idx.dt.tz_convert(args.tz)
    df = df.set_index(idx).sort_index()
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    out = df.resample(args.freq, label="left", closed="left").agg(agg).dropna(subset=["open", "high", "low", "close"])
    if "contract" in df.columns:
        out["contract"] = df["contract"].resample(args.freq, label="left", closed="left").last().reindex(out.index)
    if "roll_day" in df.columns:
        out["roll_day"] = df["roll_day"].resample(args.freq, label="left", closed="left").max().reindex(out.index).fillna(0).astype(int)
    out.index.name = "timestamp"
    args.out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out_path)
    print(f"wrote {len(out):,} bars -> {args.out_path}")


if __name__ == "__main__":
    main()
