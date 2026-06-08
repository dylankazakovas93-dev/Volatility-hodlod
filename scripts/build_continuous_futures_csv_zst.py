#!/usr/bin/env python3
"""Build daily front-month continuous futures bars from a CSV or CSV.zst dump.

For each UTC date, choose the standard contract matching the symbol root with
the highest total volume, then keep only that contract's rows for that day.
This mirrors scripts/build_gc_continuous.py but supports compressed CSV input
and arbitrary roots such as NQ.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
from collections import defaultdict
from pathlib import Path


MONTH_CODES = "FGHJKMNQUVXZ"


def open_text(path: Path):
    if path.suffix == ".zst":
        import zstandard as zstd

        fh = path.open("rb")
        reader = zstd.ZstdDecompressor().stream_reader(fh)
        return io.TextIOWrapper(reader, encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def contract_re(root: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(root)}[{MONTH_CODES}]\d$")


def pick_front_month(in_path: Path, root: str) -> dict[str, str]:
    pattern = contract_re(root)
    volume_by_day_symbol: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    with open_text(in_path) as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            sym = row["symbol"]
            if not pattern.match(sym):
                continue
            date = row["ts_event"][:10]
            volume_by_day_symbol[date][sym] += int(row["volume"])
    return {date: max(vols.items(), key=lambda kv: kv[1])[0] for date, vols in volume_by_day_symbol.items()}


def write_continuous(in_path: Path, out_path: Path, root: str, front_month: dict[str, str]) -> int:
    pattern = contract_re(root)
    prev_symbol = None
    n_written = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open_text(in_path) as fin, out_path.open("w", encoding="utf-8", newline="") as fout:
        reader = csv.DictReader(fin)
        writer = csv.writer(fout)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume", "contract", "roll_day"])
        for row in reader:
            sym = row["symbol"]
            if not pattern.match(sym):
                continue
            date = row["ts_event"][:10]
            if front_month.get(date) != sym:
                continue
            roll_day = prev_symbol is not None and prev_symbol != sym
            writer.writerow([row["ts_event"], row["open"], row["high"], row["low"], row["close"], row["volume"], sym, int(roll_day)])
            prev_symbol = sym
            n_written += 1
    return n_written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="in_path", required=True, type=Path)
    parser.add_argument("--out", dest="out_path", required=True, type=Path)
    parser.add_argument("--root", required=True, help="contract root, e.g. GC or NQ")
    args = parser.parse_args()

    print("pass 1/2: computing daily volume per contract ...")
    front_month = pick_front_month(args.in_path, args.root)
    print(f"  resolved front-month contract for {len(front_month)} days")
    rolls = sorted(front_month.items())
    changes = [(d, s) for (d, s), (_, ps) in zip(rolls[1:], rolls[:-1]) if s != ps]
    print(f"  {len(changes)} contract changes across the period")
    for d, s in changes[:20]:
        print(f"    -> {d}: rolled to {s}")

    print("pass 2/2: writing continuous series ...")
    n = write_continuous(args.in_path, args.out_path, args.root, front_month)
    print(f"  wrote {n:,} bars -> {args.out_path}")


if __name__ == "__main__":
    main()
