#!/usr/bin/env python3
"""Stage 4: attaches causal GARCH volatility-percentile bucket and HMM
(2-state, 3-state) filtered regime state to every development-year E-F
touch (whether or not it ends up executed), for later regime-gated
replay.

Usage:
    python3 scripts/build_stage4_regime_features.py --bars ... --out-dir outputs
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np
import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.data_loader import load_1m_ohlcv  # noqa: E402
from scripts.run_stage1_simple_surface import build_master_table  # noqa: E402
from scripts.stage2_engine import (  # noqa: E402
    fit_frozen_formula, apply_frozen_formula, DEV_YEARS,
    minutes_since_session_start, window_allows,
)
from scripts.stage4_regime_data import build_5min_bars, session_order  # noqa: E402
from scripts.stage4_garch import build_garch_forecast_cache, forecast_before  # noqa: E402
from scripts.stage4_hmm import build_features as build_hmm_features, build_hmm_state_cache, state_before  # noqa: E402

WINDOW_BLOCKS = set("EF")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", required=True)
    ap.add_argument("--out-dir", default="outputs")
    args = ap.parse_args()
    out_dir = os.path.join(REPO_ROOT, args.out_dir)

    bars_1m = load_1m_ohlcv(args.bars)
    master = build_master_table(out_dir)
    master["conventional_mfe_pts"] = master["mfe"].clip(lower=0)
    master["conventional_mae_pts"] = (-master["mae"]).clip(lower=0)
    frozen = fit_frozen_formula(master, 0.50, 0.50, DEV_YEARS)
    full_df = apply_frozen_formula(master, frozen)

    dev = full_df[full_df["year"].isin(DEV_YEARS)].copy()
    dev["touched_at"] = pd.to_datetime(dev["touched_at"], utc=True)
    dev["minutes_elapsed"] = dev.apply(
        lambda r: minutes_since_session_start(r["touched_at"], r["session_date"]), axis=1)
    dev["in_ef"] = dev["minutes_elapsed"].apply(lambda m: window_allows(WINDOW_BLOCKS, m))
    ef = dev[dev["in_ef"]].copy()
    print(f"E-F touches needing regime features: {len(ef)}", file=sys.stderr)

    t0 = time.time()
    bars_5m = build_5min_bars(bars_1m)
    all_sessions = session_order(bars_5m)
    print(f"5-min bars built in {time.time()-t0:.1f}s, {len(all_sessions)} sessions", file=sys.stderr)

    sessions_needed = sorted(ef["session_date"].unique())
    print(f"distinct sessions needing fits: {len(sessions_needed)}", file=sys.stderr)

    t0 = time.time()
    garch_cache = build_garch_forecast_cache(bars_5m, all_sessions, sessions_needed)
    print(f"GARCH fits done in {time.time()-t0:.1f}s", file=sys.stderr)

    hmm_feat = build_hmm_features(bars_5m)
    t0 = time.time()
    hmm2_cache = build_hmm_state_cache(hmm_feat, all_sessions, sessions_needed, n_states=2)
    print(f"HMM 2-state fits done in {time.time()-t0:.1f}s", file=sys.stderr)
    t0 = time.time()
    hmm3_cache = build_hmm_state_cache(hmm_feat, all_sessions, sessions_needed, n_states=3)
    print(f"HMM 3-state fits done in {time.time()-t0:.1f}s", file=sys.stderr)

    records = []
    for _, row in ef.iterrows():
        sess, ts = row["session_date"], row["touched_at"]
        garch_var = forecast_before(garch_cache, sess, ts)
        h2_label, h2_prob = state_before(hmm2_cache, sess, ts)
        h3_label, h3_prob = state_before(hmm3_cache, sess, ts)
        records.append({
            "level_id": row["level_id"], "garch_variance": garch_var,
            "hmm2_state": h2_label, "hmm2_prob": h2_prob,
            "hmm3_state": h3_label, "hmm3_prob": h3_prob,
        })
    regime_df = pd.DataFrame(records)

    # causal GARCH percentile rank: percentile of each forecast among ALL
    # PRIOR forecasts (chronological, using only forecasts from earlier
    # dev-year E-F touches -- ranked against the same population being
    # traded, not the full historical distribution)
    ef_sorted = ef.merge(regime_df, on="level_id").sort_values("touched_at").reset_index(drop=True)
    percentiles = []
    seen = []
    for v in ef_sorted["garch_variance"]:
        if v is None or pd.isna(v) or len(seen) < 20:
            percentiles.append(None)
        else:
            pct = float((np.array(seen) < v).mean() * 100)
            percentiles.append(pct)
        if v is not None and not pd.isna(v):
            seen.append(v)
    ef_sorted["garch_percentile"] = percentiles

    out_path = os.path.join(out_dir, "stage4_regime_features.csv")
    ef_sorted.to_csv(out_path, index=False)

    summary = {
        "n_touches": len(ef_sorted),
        "n_sessions": len(sessions_needed),
        "garch_missing": int(ef_sorted["garch_variance"].isna().sum()),
        "hmm2_missing": int(ef_sorted["hmm2_state"].isna().sum()),
        "hmm3_missing": int(ef_sorted["hmm3_state"].isna().sum()),
    }
    with open(os.path.join(out_dir, "stage4_regime_features_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
