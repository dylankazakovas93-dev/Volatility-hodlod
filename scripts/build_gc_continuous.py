#!/usr/bin/env python3
"""Build a single continuous 1-minute GC OHLCV series from a raw Databento
GLBX MDP3 dump that contains many overlapping contracts (front-month,
back-months, micros (MGC...), and calendar spreads (e.g. GCM6-GCQ6)).

Strategy: for each UTC calendar day, pick the standard GC contract
(symbols matching GC<month-code><single-digit-year>, e.g. GCQ4 — this
excludes micros and spreads) with the highest traded volume that day,
and use *only* that contract's bars for the day. This is the standard
"front month by volume" continuous-contract construction.

NOTE: this does NOT back-adjust prices across contract rolls (no Panama/
ratio adjustment). On a roll day there can be a real price gap between
the outgoing and incoming contract — the output CSV marks every bar with
its source `contract` and a `roll_day` flag so that gap is auditable
rather than hidden. When testing the indicator's *persistent untouched
levels* (which can survive across days), be aware a roll-day gap could
produce a "touch" that wouldn't occur on a back-adjusted continuous chart
— cross-check any such hits against the `roll_day` flag.

Usage:
    python3 scripts/build_gc_continuous.py \
        --in /tmp/gc_data.csv \
        --out data/gc_1m/gc_continuous_1m.csv
"""
import argparse
import csv
import re
from collections import defaultdict

CONTRACT_RE = re.compile(r"^GC[FGHJKMNQUVXZ]\d$")


def pick_front_month(in_path: str) -> dict[str, str]:
    """First pass: total volume per (date, symbol) -> front-month symbol per date."""
    volume_by_day_symbol: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    with open(in_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sym = row["symbol"]
            if not CONTRACT_RE.match(sym):
                continue
            date = row["ts_event"][:10]
            volume_by_day_symbol[date][sym] += int(row["volume"])

    front_month = {}
    for date, vols in volume_by_day_symbol.items():
        front_month[date] = max(vols.items(), key=lambda kv: kv[1])[0]
    return front_month


def write_continuous(in_path: str, out_path: str, front_month: dict[str, str]) -> int:
    """Second pass: keep only bars from each day's chosen front-month contract."""
    prev_symbol = None
    n_written = 0

    with open(in_path, newline="") as fin, open(out_path, "w", newline="") as fout:
        reader = csv.DictReader(fin)
        writer = csv.writer(fout)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume", "contract", "roll_day"])

        for row in reader:
            sym = row["symbol"]
            if not CONTRACT_RE.match(sym):
                continue
            date = row["ts_event"][:10]
            if front_month.get(date) != sym:
                continue

            roll_day = prev_symbol is not None and prev_symbol != sym
            writer.writerow(
                [
                    row["ts_event"],
                    row["open"],
                    row["high"],
                    row["low"],
                    row["close"],
                    row["volume"],
                    sym,
                    int(roll_day),
                ]
            )
            prev_symbol = sym
            n_written += 1

    return n_written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="in_path", required=True, help="path to decompressed raw OHLCV-1m CSV")
    parser.add_argument("--out", dest="out_path", required=True, help="output path for the continuous series CSV")
    args = parser.parse_args()

    print("pass 1/2: computing daily volume per contract ...")
    front_month = pick_front_month(args.in_path)
    print(f"  resolved front-month contract for {len(front_month)} days")

    rolls = sorted(
        (date, sym)
        for date, sym in front_month.items()
    )
    changes = [(d, s) for (d, s), (pd_, ps) in zip(rolls[1:], rolls[:-1]) if s != ps]
    print(f"  {len(changes)} contract changes across the period, e.g.:")
    for d, s in changes[:15]:
        print(f"    -> {d}: rolled to {s}")

    print("pass 2/2: writing continuous series ...")
    n = write_continuous(args.in_path, args.out_path, front_month)
    print(f"  wrote {n:,} bars -> {args.out_path}")


if __name__ == "__main__":
    main()
