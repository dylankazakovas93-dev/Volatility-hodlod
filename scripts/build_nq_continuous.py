#!/usr/bin/env python3
"""Builds the canonical NQ continuous 1-minute series from raw Databento
GLBX.MDP3 ohlcv-1m dumps (dataset=GLBX.MDP3, schema=ohlcv-1m, symbols=NQ.FUT,
stype_in=parent -- i.e. every individual NQ futures contract + calendar
spreads under the NQ.FUT parent symbol, at once).

Rule (verified byte-for-byte against the canonical file across all
2,964,655 rows, 2018-01-01 -> 2026-06-07): for each UTC calendar day, keep
only the standard quarterly contract (symbol matches NQ[HMUZ]\\d, i.e.
excludes calendar-spread symbols like "NQH8-NQM8") with the highest total
traded volume that day, and use only that contract's bars for the day.
This is the same methodology documented for the GC pipeline
(scripts/build_gc_continuous.py in the research repository) -- not a new
rule invented for this handoff.

Not adjusted across rolls: every bar keeps its actual traded price; roll
days are logged via the `roll_day` column so gaps stay auditable.

Note on causality: this rule decides day D's active contract using day D's
own full-day volume total, not only information available before day D
starts. This is a same-day, not strictly pre-day-causal, selection -- see
docs/DATA_PIPELINE.md for the full discussion.

Usage:
    python3 scripts/build_nq_continuous.py \
        --raw glbx-mdp3-20180101-20191230.ohlcv-1m.csv \
        --raw glbx-mdp3-20200101-20201230.ohlcv-1m.csv \
        --raw glbx-mdp3-20210101-20221230.ohlcv-1m.csv \
        --raw glbx-mdp3-20230101-20241230.ohlcv-1m.csv \
        --raw glbx-mdp3-20250101-20260607.ohlcv-1m.csv \
        --out data/nq_1m/nq_continuous_2018_2026_1m.csv

Each --raw file is the decompressed CSV (`zstd -d <file>.csv.zst`) from a
Databento batch download job with query:
    {"dataset": "GLBX.MDP3", "schema": "ohlcv-1m", "symbols": ["NQ.FUT"],
     "stype_in": "parent", "stype_out": "instrument_id"}
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

STANDARD_CONTRACT_RE = r"^NQ[HMUZ]\d$"


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
