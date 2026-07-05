#!/usr/bin/env python3
"""Stage 1 corrections to the Stage 0 excursion dataset (section 6 of the
Stage 1 spec). Does NOT overwrite or remove any original Stage 0 field --
only adds new, explicitly named columns on top of
outputs/stage0_signal_paths.csv.

A. Signed path extrema: Stage 0's `mfe`/`mae` columns are already the
   signed favourable/adverse excursion (fav = high-entry for a long /
   entry-low for a short; adv = low-entry for a long / entry-high for a
   short) -- retained verbatim here as `signed_mfe_pts` / `signed_mae_pts`.

B. Conventional (nonnegative) MFE/MAE:
     conventional_mfe_pts = max(0, signed_mfe_pts)
     conventional_mae_pts = max(0, -signed_mae_pts)   (a positive loss magnitude)

Usage:
    python3 scripts/fix_stage0_definitions.py --out-dir outputs
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()
    out_dir = os.path.join(REPO_ROOT, args.out_dir)

    df = pd.read_csv(os.path.join(out_dir, "stage0_signal_paths.csv"))

    df["signed_mfe_pts"] = df["mfe"]
    df["signed_mae_pts"] = df["mae"]
    df["conventional_mfe_pts"] = np.maximum(0.0, df["signed_mfe_pts"])
    df["conventional_mae_pts"] = np.maximum(0.0, -df["signed_mae_pts"])

    n_negative_signed_mfe = int((df["signed_mfe_pts"] < 0).sum())
    n_positive_signed_mae = int((df["signed_mae_pts"] > 0).sum())

    parquet_path = os.path.join(out_dir, "stage1_corrected_excursions.parquet")
    df.to_parquet(parquet_path, index=False)

    def sha256_file(path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def git_sha():
        try:
            return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT).decode().strip()
        except Exception:
            return None

    summary = {
        "research_commit": git_sha(),
        "n_signals": len(df),
        "n_negative_signed_mfe": n_negative_signed_mfe,
        "n_positive_signed_mae": n_positive_signed_mae,
        "expected_n_negative_signed_mfe": 72,
        "expected_n_positive_signed_mae": 76,
        "reconciled": n_negative_signed_mfe == 72 and n_positive_signed_mae == 76,
        "output_parquet": parquet_path,
        "output_parquet_sha256": sha256_file(parquet_path),
        "reproduction_command": f"python3 scripts/fix_stage0_definitions.py --out-dir {args.out_dir}",
    }
    with open(os.path.join(out_dir, "stage1_corrected_excursions_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
