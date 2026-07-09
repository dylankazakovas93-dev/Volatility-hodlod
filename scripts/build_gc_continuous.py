#!/usr/bin/env python3
"""Builds a canonical GC (COMEX Gold futures) continuous 1-minute series from
raw Databento GLBX.MDP3 ohlcv-1m dumps, using the exact same roll rule as
scripts/build_nq_continuous.py (documented in docs/DATA_PIPELINE.md as the
GC methodology this repo's NQ pipeline was itself modeled on): for each UTC
calendar day, keep only the standard outright contract (excludes calendar
spreads like "GCF4-GCG4" and the separate MGC micro-gold product) with the
highest total traded volume that day, and use only that contract's bars for
the day.

GC differs from NQ only in which month letters are valid: NQ is quarterly
(H/M/U/Z) while GC lists a contract most calendar months
(F/G/H/J/K/M/N/Q/U/V/X/Z all observed in the raw data) -- the regex below
reflects that, everything else is identical to the NQ script.

Usage:
    python3 scripts/build_gc_continuous.py \
        --raw glbx-mdp3-20230601-20260531.ohlcv-1m.csv \
        --out data/gc_1m/gc_continuous_2023_2026_1m.csv
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

STANDARD_CONTRACT_RE = r"^GC[FGHJKMNQUVXZ]\d$"


def build_segment(raw_path: str) -> pd.DataFrame:
    raw = pd.read_csv(raw_path, usecols=["ts_event", "open", "high", "low", "close", "volume", "symbol"])
    raw["ts_event"] = pd.to_datetime(raw["ts_event"], utc=True)
    raw["date"] = raw["ts_event"].dt.date

    standard = raw[raw["symbol"].str.match(STANDARD_CONTRACT_RE)].copy()

    daily_volume = standard.groupby(["date", "symbol"])["volume"].sum().reset_index()
    winner = (
        daily_volume.loc[daily_volume.groupby("date")["volume"].idxmax()]
        [["date", "symbol"]]
        .rename(columns={"symbol": "winner"})
    )

    merged = standard.merge(winner, on="date")
    kept = merged[merged["symbol"] == merged["winner"]].sort_values("ts_event")
    return kept[["ts_event", "open", "high", "low", "close", "volume", "symbol"]].rename(
        columns={"ts_event": "timestamp", "symbol": "contract"}
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", action="append", required=True,
                     help="decompressed raw Databento CSV; repeat for multiple date-range files")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    parts = [build_segment(p) for p in args.raw]
    full = pd.concat(parts).drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)

    full["roll_day"] = (full["contract"] != full["contract"].shift(1)).astype(int)
    if len(full):
        full.loc[0, "roll_day"] = 0

    full.to_csv(args.out, index=False)
    print(f"wrote {len(full)} rows to {args.out}")
    print(f"span: {full['timestamp'].iloc[0]} -> {full['timestamp'].iloc[-1]}")
    print(f"contracts used: {full['contract'].nunique()}, roll days: {int(full['roll_day'].sum())}")


if __name__ == "__main__":
    sys.exit(main())
