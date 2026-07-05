#!/usr/bin/env python3
"""Computes a pandas/serialization-independent content fingerprint for the
canonical NQ bars CSV. Used only for verification diagnostics -- does not
affect and is never read by src/strict_engine.py or
src/independent_strict_engine.py.

Each row is normalized to a fixed, explicit string form:

    <UTC ISO8601 timestamp>|<open Decimal>|<high Decimal>|<low Decimal>|
    <close Decimal>|<int volume>|<contract>|<int roll_day>\n

and streamed into a single SHA-256, so two files that differ only in
pandas/numpy CSV float-formatting, header spelling, or line-ending
convention -- but agree on every field's actual value -- produce the same
normalized hash.

Usage:
    python3 scripts/normalized_content_hash.py --bars data/nq_1m/nq_continuous_2018_2026_1m.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from datetime import datetime, timezone
from decimal import Decimal


def normalize_timestamp(raw: str) -> str:
    ts = datetime.fromisoformat(raw)
    if ts.tzinfo is None:
        raise ValueError(f"naive timestamp not allowed: {raw!r}")
    return ts.astimezone(timezone.utc).isoformat()


def normalize_row(row: dict) -> bytes:
    ts = normalize_timestamp(row["timestamp"])
    o = Decimal(row["open"]).normalize()
    h = Decimal(row["high"]).normalize()
    l = Decimal(row["low"]).normalize()
    c = Decimal(row["close"]).normalize()
    vol = int(Decimal(row["volume"]))
    contract = row["contract"]
    roll_day = int(Decimal(row["roll_day"]))
    line = f"{ts}|{o}|{h}|{l}|{c}|{vol}|{contract}|{roll_day}\n"
    return line.encode("utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    args = ap.parse_args()

    h = hashlib.sha256()
    n = 0
    with open(args.bars, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            h.update(normalize_row(row))
            n += 1

    print(f"rows normalized : {n}")
    print(f"normalized sha256: {h.hexdigest()}")


if __name__ == "__main__":
    sys.exit(main())
