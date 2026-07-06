#!/usr/bin/env python3
"""Stage 5: extends the causal rolling 3-state HMM state/probability cache
to every development-year touch in the 18:00-11:00 ET span (all blocks
A-I), not just the E-F (08:00-11:00) touches from Stage 4 -- needed
because Stage 5 tests much wider entry windows. Reuses the exact same
per-session HMM fitting/forward-filtering code as Stage 4 (no re-design).

Usage:
    python3 scripts/build_stage5_hmm3_features.py --bars ... --out-dir outputs
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import pandas as pd

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.data_loader import load_1m_ohlcv  # noqa: E402
from scripts.run_stage1_simple_surface import build_master_table  # noqa: E402
from scripts.stage2_engine import (  # noqa: E402
    fit_frozen_formula, apply_frozen_formula, DEV_YEARS, minutes_since_session_start,
)
from scripts.stage4_regime_data import build_5min_bars, session_order  # noqa: E402
from scripts.stage4_hmm import build_features as build_hmm_features, build_hmm_state_cache, state_before  # noqa: E402

WIDE_WINDOW_END_MINUTES = 1020  # 18:00 -> 11:00 next day


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
    wide = dev[(dev["minutes_elapsed"] >= 0) & (dev["minutes_elapsed"] < WIDE_WINDOW_END_MINUTES)].copy()
    print(f"touches needing HMM3 features: {len(wide)}", file=sys.stderr)

    t0 = time.time()
    bars_5m = build_5min_bars(bars_1m)
    all_sessions = session_order(bars_5m)
    print(f"5-min bars built in {time.time()-t0:.1f}s", file=sys.stderr)

    sessions_needed = sorted(wide["session_date"].unique())
    print(f"distinct sessions needing HMM3 fits: {len(sessions_needed)}", file=sys.stderr)

    hmm_feat = build_hmm_features(bars_5m)
    t0 = time.time()
    hmm3_cache = build_hmm_state_cache(hmm_feat, all_sessions, sessions_needed, n_states=3)
    print(f"HMM 3-state fits done in {time.time()-t0:.1f}s", file=sys.stderr)

    records = []
    for _, row in wide.iterrows():
        sess, ts = row["session_date"], row["touched_at"]
        h3_label, h3_prob = state_before(hmm3_cache, sess, ts)
        records.append({"level_id": row["level_id"], "hmm3_state": h3_label, "hmm3_prob": h3_prob})
    regime_df = pd.DataFrame(records)

    out_path = os.path.join(out_dir, "stage5_hmm3_features.csv")
    regime_df.to_csv(out_path, index=False)

    summary = {"n_touches": len(regime_df), "n_sessions": len(sessions_needed),
               "hmm3_missing": int(regime_df["hmm3_state"].isna().sum())}
    with open(os.path.join(out_dir, "stage5_hmm3_features_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
