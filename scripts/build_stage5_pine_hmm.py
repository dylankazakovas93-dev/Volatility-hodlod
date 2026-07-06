#!/usr/bin/env python3
"""Stage 5 Part 5B: Pine-compatible FROZEN 3-state HMM.

Fits once on 2018+2020+2023 only (never refit, never touches 2026),
freezes feature standardization (mean/std), transition matrix, state
means/covariances, and state ordering (ascending by fitted average
realized-vol feature) -- then applies causal forward-filtering (same
algorithm as the rolling model) to partial-2026 data using these frozen
parameters, for direct comparison against the rolling (per-session refit)
HMM's 2026 decisions.

Usage:
    python3 scripts/build_stage5_pine_hmm.py --bars ... --out-dir outputs
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.data_loader import load_1m_ohlcv  # noqa: E402
from scripts.stage4_regime_data import build_5min_bars  # noqa: E402
from scripts.stage4_hmm import build_features, causal_forward_filter, N_ITER, SEED  # noqa: E402

FREEZE_YEARS = {2018, 2020, 2023}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()
    out_dir = os.path.join(REPO_ROOT, args.out_dir)

    bars_1m = load_1m_ohlcv(args.bars)
    bars_5m = build_5min_bars(bars_1m)
    feat = build_features(bars_5m)

    # research_session_date's "year" is the session's own label year -- use
    # the session_date's leading 4 chars, not the bar timestamp's year
    feat["session_year"] = feat["session_date"].str[:4].astype(int)

    train = feat[feat["session_year"].isin(FREEZE_YEARS)].dropna(subset=["ret", "vol30", "trend30"])
    print(f"frozen-fit training rows: {len(train)}", file=sys.stderr)

    mu = train[["ret", "vol30", "trend30"]].mean()
    sd = train[["ret", "vol30", "trend30"]].std().replace(0, 1.0)
    X_train = ((train[["ret", "vol30", "trend30"]] - mu) / sd).to_numpy()

    model = GaussianHMM(n_components=3, covariance_type="diag", n_iter=N_ITER,
                         random_state=SEED, tol=1e-3)
    model.fit(X_train)
    vol_means = model.means_[:, 1]
    order = np.argsort(vol_means)
    labels = ["LOW_VOL", "MID_VOL", "HIGH_VOL"]

    frozen_params = {
        "mu": mu.to_dict(), "sd": sd.to_dict(),
        "startprob": model.startprob_.tolist(), "transmat": model.transmat_.tolist(),
        "means": model.means_.tolist(), "covars": model.covars_.tolist(),
        "state_order": order.tolist(), "labels": labels,
    }
    with open(os.path.join(out_dir, "stage5_pine_hmm_frozen_params.json"), "w") as f:
        json.dump(frozen_params, f, indent=2)

    # apply frozen params to 2026 sessions only, WITHOUT any refitting
    sessions_2026 = sorted(feat.loc[feat["session_year"] == 2026, "session_date"].unique())
    print(f"2026 sessions: {len(sessions_2026)}", file=sys.stderr)

    cache = {}
    for sess in sessions_2026:
        sess_feat = feat[feat["session_date"] == sess].dropna(subset=["ret", "vol30", "trend30"])
        if sess_feat.empty:
            continue
        X = ((sess_feat[["ret", "vol30", "trend30"]] - mu) / sd).to_numpy()
        alpha = causal_forward_filter(model, X)
        ordered_alpha = alpha[:, order]
        max_state_idx = ordered_alpha.argmax(axis=1)
        max_prob = ordered_alpha.max(axis=1)
        df = pd.DataFrame({"state_label": [labels[i] for i in max_state_idx], "max_prob": max_prob},
                           index=sess_feat.index)
        cache[sess] = df

    # save as a level_id-keyed feature table matching the rolling-HMM format,
    # for the 2026 development-year touches only
    from scripts.run_stage1_simple_surface import build_master_table
    from scripts.stage2_engine import fit_frozen_formula, apply_frozen_formula, DEV_YEARS
    from scripts.stage4_hmm import state_before

    master = build_master_table(out_dir)
    master["conventional_mfe_pts"] = master["mfe"].clip(lower=0)
    master["conventional_mae_pts"] = (-master["mae"]).clip(lower=0)
    frozen_tpsl = fit_frozen_formula(master, 0.50, 0.50, DEV_YEARS)
    full_df = apply_frozen_formula(master, frozen_tpsl)
    touches_2026 = full_df[full_df["year"] == 2026].copy()
    touches_2026["touched_at"] = pd.to_datetime(touches_2026["touched_at"], utc=True)

    records = []
    for _, row in touches_2026.iterrows():
        label, prob = state_before(cache, row["session_date"], row["touched_at"])
        records.append({"level_id": row["level_id"], "hmm3_state_pine": label, "hmm3_prob_pine": prob})
    out_path = os.path.join(out_dir, "stage5_pine_hmm_2026_features.csv")
    pd.DataFrame(records).to_csv(out_path, index=False)
    print(f"wrote {out_path}, {len(records)} touches")


if __name__ == "__main__":
    main()
