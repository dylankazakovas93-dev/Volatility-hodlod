#!/usr/bin/env python3
"""Locked OOS holdout: builds and saves (a) the rich causal rolling 3-state
HMM cache for every session containing a reserved-year (2019/2021/2022/
2024/2025) physical touch, and (b) the frozen Pine-compatible HMM applied
(no refitting) to 2024/2025 sessions only.

Chronological history for HMM training spans the FULL 2018-2026 dataset
(all_sessions), so trailing fits for early-in-reserved-year sessions
correctly draw on whatever prior sessions -- development or reserved --
precede them. Only the STATE OUTPUT is restricted to reserved-year
sessions; nothing about training eligibility is restricted by year.

Usage:
    python3 scripts/build_oos_hmm3_cache.py --bars ... --out-dir outputs
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_loader import load_1m_ohlcv  # noqa: E402
from scripts.run_stage1_simple_surface import build_master_table  # noqa: E402
from scripts.stage2_engine import fit_frozen_formula, apply_frozen_formula, DEV_YEARS, RESERVED_YEARS  # noqa: E402
from scripts.stage4_regime_data import build_5min_bars, session_order  # noqa: E402
from scripts.stage4_hmm import build_features as build_hmm_features  # noqa: E402
from scripts.oos_engine import build_rich_hmm3_cache, load_pine_frozen_params, build_pine_cache  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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

    reserved = full_df[full_df["year"].isin(RESERVED_YEARS)].copy()
    sessions_reserved = sorted(reserved["session_date"].unique())
    print(f"reserved-year touches: {len(reserved)}, distinct sessions: {len(sessions_reserved)}", file=sys.stderr)

    t0 = time.time()
    bars_5m = build_5min_bars(bars_1m)
    all_sessions = session_order(bars_5m)
    print(f"5-min bars built, {len(all_sessions)} total sessions, in {time.time()-t0:.1f}s", file=sys.stderr)

    hmm_feat = build_hmm_features(bars_5m)

    t0 = time.time()
    cache_probs, cache_meta = build_rich_hmm3_cache(hmm_feat, all_sessions, sessions_reserved, n_states=3)
    print(f"rolling HMM3 rich cache built in {time.time()-t0:.1f}s", file=sys.stderr)
    n_fit = sum(1 for v in cache_meta.values() if v is not None)
    print(f"sessions with a valid fit: {n_fit}/{len(sessions_reserved)}", file=sys.stderr)

    with open(os.path.join(out_dir, "oos_hmm3_rolling_cache.pkl"), "wb") as f:
        pickle.dump({"cache_probs": cache_probs, "cache_meta": cache_meta}, f)

    # Frozen Pine-compatible HMM, applied only to 2024/2025 sessions (never
    # refit; params were fit on 2018+2020+2023 only, so applying them to
    # 2019/2021/2022 would use parameters trained on chronologically later
    # data relative to those touches -- excluded per task instruction).
    params = load_pine_frozen_params(os.path.join(out_dir, "stage5_pine_hmm_frozen_params.json"))
    sessions_pine = sorted(reserved.loc[reserved["year"].isin([2024, 2025]), "session_date"].unique())
    t0 = time.time()
    pine_cache = build_pine_cache(hmm_feat, sessions_pine, params)
    print(f"Pine-frozen cache built for {len(sessions_pine)} sessions in {time.time()-t0:.1f}s", file=sys.stderr)
    with open(os.path.join(out_dir, "oos_pine_cache.pkl"), "wb") as f:
        pickle.dump({"cache": pine_cache}, f)

    print("done", file=sys.stderr)


if __name__ == "__main__":
    main()
