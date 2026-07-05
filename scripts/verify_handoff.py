#!/usr/bin/env python3
"""One-command fresh-clone verification: data hashes -> primary engine ->
independent engine -> row-by-row comparison -> test suite. Exits nonzero on
any failure so it can be used as a single CI-style gate.

Usage:
    python3 scripts/verify_handoff.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv \
        --vxn  data/vxn_daily_2018_2026.csv
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(cmd, **kw):
    print(f"\n$ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT, **kw)
    if result.returncode != 0:
        print(f"FAILED (exit {result.returncode}): {' '.join(cmd)}")
        sys.exit(result.returncode)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--vxn", required=True)
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()
    py = sys.executable

    run([py, "scripts/build_or_verify_data.py", "--bars", args.bars, "--vxn", args.vxn])
    run([py, "-m", "src.strict_engine", "--bars", args.bars, "--vxn", args.vxn, "--out-dir", args.out_dir])
    run([py, "-m", "src.independent_strict_engine", "--bars", args.bars, "--vxn", args.vxn, "--out-dir", args.out_dir])
    run([py, "scripts/compare_engines.py",
         "--reference", os.path.join(args.out_dir, "baseline_executed.csv"),
         "--comparison", os.path.join(args.out_dir, "independent_executed.csv")])
    run([py, "-m", "pytest", "tests/", "-v"])

    print("\n=== HANDOFF VERIFICATION: PASS ===")


if __name__ == "__main__":
    main()
