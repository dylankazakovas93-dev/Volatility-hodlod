#!/usr/bin/env python3
"""Stage 0 MAE/MFE distribution, path-ordering, and normalized-scale
stability reporting. Read-only over stage0_signal_paths.csv +
stage0_features.csv; fits/selects nothing.

Usage:
    python3 scripts/report_stage0_excursions.py --out-dir outputs
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

PCTS = [0.25, 0.50, 0.60, 0.70, 0.75, 0.80, 0.90, 0.95]
SCALE_COLS = ["range_15m", "range_30m", "range_60m", "range_120m", "prev_session_range",
              "atr14_5m", "atr14_15m", "atr14_30m", "atr14_60m",
              "ewma_vol_hl30m", "ewma_vol_hl60m", "ewma_vol_hl120m"]


def quantile_row(series):
    s = series.dropna()
    row = {"n": len(s), "mean": s.mean()}
    for p in PCTS:
        row[f"p{int(p*100)}"] = s.quantile(p)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()
    out_dir = os.path.join(REPO_ROOT, args.out_dir)

    paths = pd.read_csv(os.path.join(out_dir, "stage0_signal_paths.csv"))
    feats = pd.read_csv(os.path.join(out_dir, "stage0_features.csv"))
    df = paths.merge(feats, on=["level_id", "touched_at"], how="left")
    df["touched_at"] = pd.to_datetime(df["touched_at"], utc=True)

    # ---------------- excursion quantiles: overall / year / side / with-without 2026
    quantile_rows = []
    for label, sub in [("overall", df), ("ex_2026", df[df["year"] != 2026])]:
        for metric in ("mfe", "mae"):
            r = quantile_row(sub[metric])
            r.update({"group": label, "metric": metric})
            quantile_rows.append(r)
    for yr, sub in df.groupby("year"):
        for metric in ("mfe", "mae"):
            r = quantile_row(sub[metric])
            r.update({"group": f"year_{yr}", "metric": metric})
            quantile_rows.append(r)
    for side, sub in df.groupby("side"):
        for metric in ("mfe", "mae"):
            r = quantile_row(sub[metric])
            r.update({"group": f"side_{side}", "metric": metric})
            quantile_rows.append(r)

    # volatility quintile (by atr14_60m) and RVOL quintile (by rvol_60m_hist20)
    for feat_col, name in [("atr14_60m", "vol_quintile"), ("rvol_60m_hist20", "rvol_quintile")]:
        valid = df.dropna(subset=[feat_col])
        try:
            q = pd.qcut(valid[feat_col], 5, labels=[1, 2, 3, 4, 5], duplicates="drop")
        except ValueError:
            continue
        valid = valid.assign(_q=q)
        for qv, sub in valid.groupby("_q", observed=True):
            for metric in ("mfe", "mae"):
                r = quantile_row(sub[metric])
                r.update({"group": f"{name}_{qv}", "metric": metric})
                quantile_rows.append(r)

    quantiles_df = pd.DataFrame(quantile_rows).sort_values(["metric", "group"]).reset_index(drop=True)
    quantiles_df.to_csv(os.path.join(out_dir, "stage0_excursion_quantiles.csv"), index=False)

    # ---------------- by-year summary table
    by_year = df.groupby("year").agg(
        n=("mfe", "size"),
        mfe_mean=("mfe", "mean"), mfe_median=("mfe", "median"),
        mae_mean=("mae", "mean"), mae_median=("mae", "median"),
        cutoff_pnl_mean=("cutoff_pnl", "mean"),
        frac_mae_before_mfe=("mae_before_mfe", "mean"),
    ).reset_index()
    by_year.to_csv(os.path.join(out_dir, "stage0_excursion_by_year.csv"), index=False)

    # ---------------- path ordering
    ordering_rows = [{
        "group": "overall",
        "n": len(df),
        "frac_mae_strictly_before_mfe": float((df["mae_ts"] < df["mfe_ts"]).mean()),
        "frac_mfe_strictly_before_mae": float((df["mfe_ts"] < df["mae_ts"]).mean()),
        "frac_same_bar": float((df["mae_ts"] == df["mfe_ts"]).mean()),
        "median_minutes_to_mfe": float(df["minutes_to_mfe"].median()),
        "median_minutes_to_mae": float(df["minutes_to_mae"].median()),
    }]
    for side, sub in df.groupby("side"):
        ordering_rows.append({
            "group": f"side_{side}", "n": len(sub),
            "frac_mae_strictly_before_mfe": float((sub["mae_ts"] < sub["mfe_ts"]).mean()),
            "frac_mfe_strictly_before_mae": float((sub["mfe_ts"] < sub["mae_ts"]).mean()),
            "frac_same_bar": float((sub["mae_ts"] == sub["mfe_ts"]).mean()),
            "median_minutes_to_mfe": float(sub["minutes_to_mfe"].median()),
            "median_minutes_to_mae": float(sub["minutes_to_mae"].median()),
        })
    pd.DataFrame(ordering_rows).to_csv(os.path.join(out_dir, "stage0_path_ordering.csv"), index=False)

    # ---------------- normalized-scale stability + correlation
    stability_rows = []
    for scale in SCALE_COLS:
        valid = df.dropna(subset=[scale])
        valid = valid[valid[scale] > 0]
        if len(valid) < 30:
            continue
        norm_mfe = valid["mfe"] / valid[scale]
        norm_mae = valid["mae"].abs() / valid[scale]

        annual_med_mfe = norm_mfe.groupby(valid["year"]).median()
        annual_med_mae = norm_mae.groupby(valid["year"]).median()

        pooled_med_mfe = norm_mfe.median()
        pooled_med_mae = norm_mae.median()

        cov_mfe = float(annual_med_mfe.std() / annual_med_mfe.mean()) if annual_med_mfe.mean() else None
        cov_mae = float(annual_med_mae.std() / annual_med_mae.mean()) if annual_med_mae.mean() else None

        worst_dev_mfe = float((annual_med_mfe - pooled_med_mfe).abs().max())
        worst_dev_mae = float((annual_med_mae - pooled_med_mae).abs().max())

        ex2026_mfe = norm_mfe[valid["year"] != 2026].groupby(valid.loc[valid["year"] != 2026, "year"]).median()
        rank_stability_mfe = float(ex2026_mfe.rank().corr(annual_med_mfe.reindex(ex2026_mfe.index).rank())) if len(ex2026_mfe) > 2 else None

        stability_rows.append({
            "scale": scale,
            "n": len(valid),
            "missing_rate": float(df[scale].isna().mean()),
            "corr_with_mfe": float(df[scale].corr(df["mfe"])) if df[scale].notna().sum() > 10 else None,
            "corr_with_mae": float(df[scale].corr(df["mae"].abs())) if df[scale].notna().sum() > 10 else None,
            "cov_annual_median_norm_mfe": cov_mfe,
            "cov_annual_median_norm_mae": cov_mae,
            "worst_annual_deviation_norm_mfe": worst_dev_mfe,
            "worst_annual_deviation_norm_mae": worst_dev_mae,
            "rank_stability_ex2026_mfe": rank_stability_mfe,
        })
    stability_df = pd.DataFrame(stability_rows).sort_values("cov_annual_median_norm_mfe")
    stability_df.to_csv(os.path.join(out_dir, "stage0_feature_stability.csv"), index=False)

    # ---------------- MFE conditional on prior MAE bucket, and vice versa
    df["mae_bucket"] = pd.qcut(df["mae"].abs(), 4, labels=["q1_small", "q2", "q3", "q4_large"], duplicates="drop")
    mfe_given_mae = df.groupby("mae_bucket", observed=True)["mfe"].agg(["mean", "median", "count"])
    df["mfe_bucket"] = pd.qcut(df["mfe"], 4, labels=["q1_small", "q2", "q3", "q4_large"], duplicates="drop")
    mae_given_mfe = df.groupby("mfe_bucket", observed=True)["mae"].agg(["mean", "median", "count"])

    conditional = {
        "mfe_given_mae_bucket": json.loads(mfe_given_mae.to_json(orient="index")),
        "mae_given_mfe_bucket": json.loads(mae_given_mfe.to_json(orient="index")),
    }

    print(json.dumps({
        "n_signals": len(df),
        "overall_mfe_median": float(df["mfe"].median()),
        "overall_mae_median": float(df["mae"].median()),
        "frac_mae_before_mfe": float((df["mae_ts"] < df["mfe_ts"]).mean()),
        "top3_most_stable_scales": stability_df.head(3)["scale"].tolist() if len(stability_df) else [],
        "conditional": conditional,
    }, indent=2))

    with open(os.path.join(out_dir, "stage0_conditional_excursions.json"), "w") as f:
        json.dump(conditional, f, indent=2)


if __name__ == "__main__":
    main()
