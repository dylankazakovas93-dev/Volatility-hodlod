#!/usr/bin/env python3
"""Build ES continuous 1-minute CSV from Databento raw GLBX.MDP3 archives
(dataset=GLBX.MDP3, schema=ohlcv-1m, symbols=ES.FUT, stype_in=parent).

Rule: for each UTC calendar day, keep only the standard quarterly contract
(symbol matches ES[HMUZ]\\d) with highest total traded volume that day.

Not adjusted across rolls. Roll days logged via roll_day column.
"""
from __future__ import annotations

import argparse
import sys
import io
import os
import zipfile
import zstandard

import pandas as pd

STANDARD_CONTRACT_RE = r"^ES[HMUZ]\d$"


def read_raw_zip(zip_path: str) -> pd.DataFrame:
    zf = zipfile.ZipFile(zip_path)
    csv_zst_name = [n for n in zf.namelist() if n.endswith(".csv.zst")][0]
    data = zf.read(csv_zst_name)
    dctx = zstandard.ZstdDecompressor()
    reader = dctx.stream_reader(io.BytesIO(data))
    df = pd.read_csv(reader, usecols=["ts_event", "open", "high", "low", "close", "volume", "symbol"])
    df["ts_event"] = pd.to_datetime(df["ts_event"], utc=True)
    return df


def build_segment(raw: pd.DataFrame) -> pd.DataFrame:
    raw = raw.copy()
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
    ap.add_argument("--zip", action="append", required=True, help="ES ZIP archive (repeat for each)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    parts = []
    for z in args.zip:
        raw = read_raw_zip(z)
        seg = build_segment(raw)
        parts.append(seg)
        print(f"  {z}: {len(seg)} rows from raw segment")

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