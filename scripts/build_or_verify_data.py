#!/usr/bin/env python3
"""Verifies the canonical NQ bars + VXN files match the frozen hashes/row
count this handoff was verified against. Does NOT build data from raw
Databento files -- see docs/DATA_PIPELINE.md for why that step cannot be
fully reproduced from what is available in this handoff, and place the
files yourself per data/README.md before running this.

Usage:
    python3 scripts/build_or_verify_data.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

EXPECTED_BARS_SHA256 = "3d0228fcc17a40933d4fdc3983a8153e5bb6445ed9e743919b3eb5c516e53880"
EXPECTED_BARS_ROWS = 2964655
EXPECTED_VXN_SHA256 = "76cc072c941542183d8c82174fe4f552b0f140f9cb368c302ad51f651992dc4e"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def count_rows(path):
    with open(path) as f:
        return sum(1 for _ in f) - 1  # minus header


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    args = ap.parse_args()

    ok = True

    print("=== NQ bars ===")
    if not os.path.exists(args.bars):
        print(f"  MISSING: {args.bars} -- see data/README.md")
        ok = False
    else:
        rows = count_rows(args.bars)
        sha = sha256_file(args.bars)
        print(f"  rows   : {rows}   (expected {EXPECTED_BARS_ROWS})   "
              f"{'OK' if rows == EXPECTED_BARS_ROWS else 'MISMATCH'}")
        print(f"  sha256 : {sha}")
        print(f"           (expected {EXPECTED_BARS_SHA256})   "
              f"{'OK' if sha == EXPECTED_BARS_SHA256 else 'MISMATCH'}")
        ok = ok and rows == EXPECTED_BARS_ROWS and sha == EXPECTED_BARS_SHA256

    print("\n=== VXN daily ===")
    if not os.path.exists(args.vxn):
        print(f"  MISSING: {args.vxn} -- see data/README.md")
        ok = False
    else:
        sha = sha256_file(args.vxn)
        print(f"  sha256 : {sha}")
        print(f"           (expected {EXPECTED_VXN_SHA256})   "
              f"{'OK' if sha == EXPECTED_VXN_SHA256 else 'MISMATCH'}")
        ok = ok and sha == EXPECTED_VXN_SHA256

    print(f"\nDATA VERIFICATION: {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
