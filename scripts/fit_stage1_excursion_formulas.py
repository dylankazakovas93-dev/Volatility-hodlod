#!/usr/bin/env python3
"""Stage 1 section 13 + 15: the 36 learned MFE/MAE quantile-regression
candidates, fit per outer walk-forward fold on training years only.

Feature sets (log1p-transformed range/ATR features, log RVOL_60):
  F1: range_30m + atr14_60m + RVOL_60
  F2: range_30m + prev_session_range + RVOL_60
  F3: atr14_60m + prev_session_range + RVOL_60
  F4 (control, no RVOL): range_30m + atr14_60m + prev_session_range

MFE quantiles {0.50, 0.65, 0.80} x MAE quantiles {0.50, 0.65, 0.80)
-> 4 * 3 * 3 = 36 candidates.

Fitting: sklearn.linear_model.QuantileRegressor (pinball loss, solver
'highs', seed-independent/deterministic). KNOWN SIMPLIFICATION (documented
in docs/STAGE1_KNOWN_LIMITATIONS.md): sklearn's QuantileRegressor has no
built-in sign-constraint option, unlike a bounded LP formulation. Range/ATR
coefficients are clipped to >= 0 and the RVOL coefficient to [-0.30, 0.30]
*after* fitting, not as an in-loop constraint -- this is a pragmatic
approximation of the spec's constrained-fitting requirement, not a full
constrained quantile LP.

Predictions are clipped to the training fold's 5th/95th percentile of the
relevant conventional excursion, then expm1-transformed back to points and
tick-rounded exactly as the simple family.

Usage:
    python3 scripts/fit_stage1_excursion_formulas.py \
        --bars data/nq_1m/nq_continuous_2018_2026_1m.csv --out-dir outputs
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys

import numpy as np
import pandas as pd
from sklearn.linear_model import QuantileRegressor

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.data_loader import load_1m_ohlcv  # noqa: E402
from src.metrics import profit_factor, max_drawdown  # noqa: E402
from scripts.stage1_engine import round_tp, round_sl, run_replay  # noqa: E402
from scripts.run_stage1_simple_surface import build_master_table  # noqa: E402

MFE_QUANTILES = [0.50, 0.65, 0.80]
MAE_QUANTILES = [0.50, 0.65, 0.80]
FEATURE_SETS = {
    "F1": ["range_30m", "atr14_60m", "rvol60_primary"],
    "F2": ["range_30m", "prev_session_range", "rvol60_primary"],
    "F3": ["atr14_60m", "prev_session_range", "rvol60_primary"],
    "F4": ["range_30m", "atr14_60m", "prev_session_range"],
}
RVOL_FEATURES = {"F1", "F2", "F3"}
FOLDS = [
    (list(range(2018, 2021)), 2021),
    (list(range(2018, 2022)), 2022),
    (list(range(2018, 2023)), 2023),
    (list(range(2018, 2024)), 2024),
    (list(range(2018, 2025)), 2025),
]
SEED = 42


def design_matrix(df, feature_names):
    cols = []
    names = []
    for f in feature_names:
        if f == "rvol60_primary":
            v = np.log(df[f].fillna(1.0).clip(lower=1e-6))
            names.append("log_rvol60")
        else:
            v = np.log1p(df[f].fillna(0.0).clip(lower=0.0))
            names.append(f"log1p_{f}")
        cols.append(v.to_numpy())
    return np.column_stack(cols), names


def fit_quantile(X, y, quantile, feature_names):
    model = QuantileRegressor(quantile=quantile, alpha=0.0, solver="highs")
    model.fit(X, y)
    coefs = dict(zip(feature_names, model.coef_))
    # post-hoc sign/bound enforcement (documented simplification)
    for name in feature_names:
        if name.startswith("log1p_"):
            coefs[name] = max(0.0, coefs[name])
        elif name == "log_rvol60":
            coefs[name] = float(np.clip(coefs[name], -0.30, 0.30))
    intercept = model.intercept_
    return intercept, coefs


def predict(X, feature_names, intercept, coefs):
    pred = np.full(X.shape[0], intercept)
    for j, name in enumerate(feature_names):
        pred += X[:, j] * coefs[name]
    return pred


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--out-dir", default="outputs")
    ap.add_argument("--cost", type=float, default=1.0)
    args = ap.parse_args()
    out_dir = os.path.join(REPO_ROOT, args.out_dir)

    np.random.seed(SEED)
    bars = load_1m_ohlcv(args.bars)
    master = build_master_table(out_dir)
    master["conventional_mfe_pts"] = master["mfe"].clip(lower=0)
    master["conventional_mae_pts"] = (-master["mae"]).clip(lower=0)

    all_candidate_rows = []
    fold_result_rows = []

    for fs_name, feat_cols in FEATURE_SETS.items():
        for mfe_q, mae_q in itertools.product(MFE_QUANTILES, MAE_QUANTILES):
            cid = f"learned|fs={fs_name}|mfeq={mfe_q:.2f}|maeq={mae_q:.2f}"
            for train_years, test_year in FOLDS:
                train_mask = master["year"].isin(train_years)
                train_df = master[train_mask].dropna(subset=feat_cols + ["conventional_mfe_pts", "conventional_mae_pts"])
                if len(train_df) < 50:
                    continue

                X_train, fnames = design_matrix(train_df, feat_cols)
                y_mfe = np.log1p(train_df["conventional_mfe_pts"].to_numpy())
                y_mae = np.log1p(train_df["conventional_mae_pts"].to_numpy())

                tp_intercept, tp_coefs = fit_quantile(X_train, y_mfe, mfe_q, fnames)
                sl_intercept, sl_coefs = fit_quantile(X_train, y_mae, mae_q, fnames)

                mfe_lo, mfe_hi = np.percentile(train_df["conventional_mfe_pts"], [5, 95])
                mae_lo, mae_hi = np.percentile(train_df["conventional_mae_pts"], [5, 95])

                full_df = master.dropna(subset=feat_cols).copy()
                X_full, _ = design_matrix(full_df, feat_cols)
                pred_log_mfe = predict(X_full, fnames, tp_intercept, tp_coefs)
                pred_log_mae = predict(X_full, fnames, sl_intercept, sl_coefs)
                pred_mfe = np.clip(np.expm1(pred_log_mfe), mfe_lo, mfe_hi)
                pred_mae = np.clip(np.expm1(pred_log_mae), mae_lo, mae_hi)

                full_df["tp_dist_stage1"] = round_tp(pd.Series(pred_mfe, index=full_df.index))
                full_df["sl_dist_stage1"] = round_sl(pd.Series(pred_mae, index=full_df.index))

                clip_frac_test = float(
                    (((full_df.loc[full_df["year"] == test_year, "tp_dist_stage1"] <= mfe_lo + 1e-9) |
                      (full_df.loc[full_df["year"] == test_year, "tp_dist_stage1"] >= mfe_hi - 1e-9)).mean())
                ) if (full_df["year"] == test_year).any() else None

                executed, skipped = run_replay(bars, full_df, "tp_dist_stage1", "sl_dist_stage1", cost_pts=args.cost)
                test_exec = executed[executed["year"] == test_year]
                pnl = test_exec["pnl_after_cost"]
                r = test_exec["r_multiple"]

                gains_pts = float(pnl[pnl > 0].sum()) if len(pnl) else 0.0
                losses_pts = float(-pnl[pnl < 0].sum()) if len(pnl) else 0.0
                gains_r = float(r[r > 0].sum()) if len(r) else 0.0
                losses_r = float(-r[r < 0].sum()) if len(r) else 0.0

                fold_result_rows.append({
                    "candidate_id": cid, "feature_set": fs_name,
                    "mfe_quantile": mfe_q, "mae_quantile": mae_q,
                    "test_year": test_year, "train_years": str(train_years),
                    "tp_coefs": json.dumps({**tp_coefs, "intercept": tp_intercept}),
                    "sl_coefs": json.dumps({**sl_coefs, "intercept": sl_intercept}),
                    "clip_fraction_test": clip_frac_test,
                    "executed": len(test_exec),
                    "net_pts": round(float(pnl.sum()), 2) if len(pnl) else 0.0,
                    "PF": round(profit_factor(pnl), 4) if len(pnl) else None,
                    "avg_R": round(float(r.mean()), 4) if len(r) else None,
                    "max_dd_R": round(max_drawdown(r), 4) if len(r) else None,
                    "gains_pts": gains_pts, "losses_pts": losses_pts,
                    "gains_r": gains_r, "losses_r": losses_r,
                })
            print(f"done {fs_name} mfeq={mfe_q} maeq={mae_q}", file=sys.stderr)

    fold_df = pd.DataFrame(fold_result_rows).sort_values(["candidate_id", "test_year"]).reset_index(drop=True)
    fold_df.to_csv(os.path.join(out_dir, "stage1_learned_walkforward.csv"), index=False)

    agg_rows = []
    for cid, grp in fold_df.groupby("candidate_id"):
        total_gains_pts = grp["gains_pts"].sum()
        total_losses_pts = grp["losses_pts"].sum()
        total_gains_r = grp["gains_r"].sum()
        total_losses_r = grp["losses_r"].sum()
        agg_rows.append({
            "candidate_id": cid,
            "feature_set": grp["feature_set"].iloc[0],
            "mfe_quantile": grp["mfe_quantile"].iloc[0],
            "mae_quantile": grp["mae_quantile"].iloc[0],
            "n_folds": len(grp),
            "aggregate_net_pts": round(float(grp["net_pts"].sum()), 2),
            # TRUE trade-level PF: pool gains/losses across all pooled trades
            # in every fold's test year, not a mistaken profit_factor() over
            # the 5 per-fold net-point totals (which wrongly treats each
            # year as a single "trade" and badly overstates PF whenever
            # wins/losses cluster by year).
            "aggregate_PF": round(total_gains_pts / total_losses_pts, 4) if total_losses_pts > 0 else None,
            "aggregate_PF_R": round(total_gains_r / total_losses_r, 4) if total_losses_r > 0 else None,
            "median_avg_R": round(float(grp["avg_R"].median()), 4),
            "n_profitable_folds": int((grp["net_pts"] > 0).sum()),
            "mean_clip_fraction": round(float(grp["clip_fraction_test"].mean()), 4),
        })
    agg_df = pd.DataFrame(agg_rows).sort_values("candidate_id").reset_index(drop=True)
    agg_df.to_csv(os.path.join(out_dir, "stage1_learned_all_candidates.csv"), index=False)

    print(agg_df.sort_values("aggregate_PF", ascending=False).head(10).to_string())


if __name__ == "__main__":
    main()
