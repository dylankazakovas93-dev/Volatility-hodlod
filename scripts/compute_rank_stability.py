#!/usr/bin/env python3
"""Stage 1 section 6D: real rank-stability diagnostics for the Stage 0
scale-feature stability table, replacing the old `rank_stability_ex2026_mfe`
column (Codex found its all-1.0 values were a self-correlation artifact --
comparing each ranking to itself rather than to an independent ranking).

For every candidate scale, this reports:
  - its coefficient-of-variation rank computed WITH 2026 included;
  - its rank computed WITH 2026 EXCLUDED;
  - the rank displacement between the two;
  - the Spearman correlation between the two COMPLETE rankings (all
    scales at once, not per-scale self-correlation);
  - whether the scale's top-3 membership changes between the two rankings.

This is descriptive only -- it does not choose or filter anything.

Usage:
    python3 scripts/compute_rank_stability.py --out-dir outputs
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

SCALE_COLS = ["range_15m", "range_30m", "range_60m", "range_120m", "prev_session_range",
              "atr14_5m", "atr14_15m", "atr14_30m", "atr14_60m",
              "ewma_vol_hl30m", "ewma_vol_hl60m", "ewma_vol_hl120m"]


def cov_of_annual_median_norm_mfe(df, scale, years):
    sub = df[df["year"].isin(years)].dropna(subset=[scale])
    sub = sub[sub[scale] > 0]
    if len(sub) < 30:
        return None
    norm_mfe = sub["conventional_mfe_pts"] / sub[scale]
    annual_med = norm_mfe.groupby(sub["year"]).median()
    if len(annual_med) < 2 or annual_med.mean() == 0:
        return None
    return float(annual_med.std() / annual_med.mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()
    out_dir = os.path.join(REPO_ROOT, args.out_dir)

    excursions = pd.read_parquet(os.path.join(out_dir, "stage1_corrected_excursions.parquet"))
    features = pd.read_csv(os.path.join(out_dir, "stage0_features.csv"))
    df = excursions.merge(features, on="level_id", suffixes=("", "_feat"))

    all_years = sorted(df["year"].unique())
    ex2026_years = [y for y in all_years if y != 2026]

    rows = []
    for scale in SCALE_COLS:
        cov_all = cov_of_annual_median_norm_mfe(df, scale, all_years)
        cov_ex = cov_of_annual_median_norm_mfe(df, scale, ex2026_years)
        rows.append({"scale": scale, "cov_with_2026": cov_all, "cov_ex_2026": cov_ex})

    stability_df = pd.DataFrame(rows)
    stability_df["rank_with_2026"] = stability_df["cov_with_2026"].rank()
    stability_df["rank_ex_2026"] = stability_df["cov_ex_2026"].rank()
    stability_df["rank_displacement"] = (stability_df["rank_with_2026"] - stability_df["rank_ex_2026"]).abs()

    valid = stability_df.dropna(subset=["rank_with_2026", "rank_ex_2026"])
    rho, pval = spearmanr(valid["rank_with_2026"], valid["rank_ex_2026"])

    top3_with = set(stability_df.nsmallest(3, "cov_with_2026")["scale"])
    top3_ex = set(stability_df.nsmallest(3, "cov_ex_2026")["scale"])
    stability_df["in_top3_with_2026"] = stability_df["scale"].isin(top3_with)
    stability_df["in_top3_ex_2026"] = stability_df["scale"].isin(top3_ex)
    stability_df["top3_membership_changed"] = stability_df["in_top3_with_2026"] != stability_df["in_top3_ex_2026"]

    out_path = os.path.join(out_dir, "stage1_rank_stability.csv")
    stability_df.sort_values("cov_ex_2026").to_csv(out_path, index=False)

    summary = {
        "spearman_rho_between_rankings": float(rho),
        "spearman_pvalue": float(pval),
        "top3_with_2026": sorted(top3_with),
        "top3_ex_2026": sorted(top3_ex),
        "top3_membership_identical": top3_with == top3_ex,
    }
    with open(os.path.join(out_dir, "stage1_rank_stability_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
