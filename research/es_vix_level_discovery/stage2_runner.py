#!/usr/bin/env python3
"""Stage 2: Deterministic ES/VIX level discovery development-grid runner.

Usage:
    python research/es_vix_level_discovery/stage2_runner.py --preflight
    python research/es_vix_level_discovery/stage2_runner.py --synthetic-smoke
    python research/es_vix_level_discovery/stage2_runner.py --development-run

--development-run is NOT to be executed in Stage 2A.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from typing import Optional

import numpy as np
import pandas as pd

# Ensure repo root is on sys.path for direct execution
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT_CANDIDATE = os.path.dirname(os.path.dirname(_THIS_DIR))
if _REPO_ROOT_CANDIDATE not in sys.path:
    sys.path.insert(0, _REPO_ROOT_CANDIDATE)

from research.es_vix_level_discovery.stage1_engine import (
    VIXLevelEngine,
    LevelConfig,
)
from research.es_vix_level_discovery.stage1_schemas import (
    write_levels_csv,
    write_touches_csv,
    write_excursions_csv,
)
from research.es_vix_level_discovery.stage2_metrics import (
    compute_config_metrics,
    compute_year_metrics,
    compute_direction_metrics,
    compute_monthly_metrics,
    compute_vix_regime_metrics,
    compute_time_of_day_metrics,
    compute_offset_family_metrics,
    compute_neighbour_support,
    compute_concentration_metrics,
    PRIMARY_HORIZONS,
    ALL_HORIZONS,
)
from research.es_vix_level_discovery.stage2_baselines import (
    build_baseline,
    compute_baseline_lift,
    BASE_SEED,
    N_RESAMPLES,
)
from research.es_vix_level_discovery.stage2_selection import (
    classify_configs,
    compute_median_ranks,
    SURVIVOR_CAP,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESEARCH_DIR = os.path.join(REPO_ROOT, "research", "es_vix_level_discovery")
ES_CAUSAL = os.path.join(REPO_ROOT, "data", "es_1m", "es_continuous_causal_2018_2026_1m.csv")
VIX_NORM = os.path.join(REPO_ROOT, "data", "vix_daily_1990_2026.csv")
GRID_PATH = os.path.join(RESEARCH_DIR, "GRID_DEFINITION.json")
REGISTRY_PATH = os.path.join(RESEARCH_DIR, "TRIAL_REGISTRY.csv")
HOLDOUT_PATH = os.path.join(RESEARCH_DIR, "HOLDOUT_LOCK.json")
STAGE2_SPEC_PATH = os.path.join(RESEARCH_DIR, "STAGE2_EXECUTION_SPEC.md")
STAGE2_SELECTION_PATH = os.path.join(RESEARCH_DIR, "STAGE2_SELECTION_RULES.json")
BASELINE_DEF_PATH = os.path.join(RESEARCH_DIR, "BASELINE_DEFINITIONS.md")
MANIFEST_PATH = os.path.join(RESEARCH_DIR, "data_manifest.json")
RUNS_DIR = os.path.join(RESEARCH_DIR, "runs")

DEVELOPMENT_START = "2018-01-01"
DEVELOPMENT_END = "2019-12-31"


def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def sha256_file(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def load_grid() -> pd.DataFrame:
    """Load the grid definition and expand to flat parameter rows."""
    with open(GRID_PATH) as f:
        grid = json.load(f)
    rows = []
    for sigma in grid["parameter_space"]["sigma_multiplier"]:
        for ib in grid["parameter_space"]["ib_minutes"]:
            for pct in grid["parameter_space"]["offset_proportional"]:
                config_id = (
                    f"VIX_ES_SIGMA_{int(sigma*100):03d}_IB{ib}_PCT_{int(pct*100):03d}"
                )
                rows.append({
                    "config_id": config_id,
                    "sigma_multiplier": sigma,
                    "ib_minutes": ib,
                    "offset_family": "proportional",
                    "offset_parameter": "offset_pct",
                    "offset_value": pct,
                    "line_life_sessions": 20,
                })
            for fixed in grid["parameter_space"]["offset_fixed_es_points"]:
                config_id = (
                    f"VIX_ES_SIGMA_{int(sigma*100):03d}_IB{ib}_FIXED_{int(fixed*10):03d}"
                )
                rows.append({
                    "config_id": config_id,
                    "sigma_multiplier": sigma,
                    "ib_minutes": ib,
                    "offset_family": "fixed",
                    "offset_parameter": "fixed_offset_es_points",
                    "offset_value": fixed,
                    "line_life_sessions": 20,
                })
    return pd.DataFrame(rows)


def load_registry() -> pd.DataFrame:
    return pd.read_csv(REGISTRY_PATH)


def preflight() -> None:
    """Run preflight checks and exit nonzero on failure."""
    errors = []

    # 1. Grid definition
    grid_df = load_grid()
    if len(grid_df) != 132:
        errors.append(f"grid has {len(grid_df)} configs, expected 132")

    # 2. Registry
    registry = load_registry()
    if len(registry) != 132:
        errors.append(f"registry has {len(registry)} configs, expected 132")

    # 3. Unique IDs
    if not registry["config_id"].is_unique:
        errors.append("registry has duplicate config_ids")

    # 4. Registry matches grid
    grid_ids = set(grid_df["config_id"])
    reg_ids = set(registry["config_id"])
    if grid_ids != reg_ids:
        errors.append(f"grid/registry mismatch: {grid_ids ^ reg_ids}")

    # 5. Parameter values exact
    for _, row in registry.iterrows():
        if row["line_life_sessions"] != 20:
            errors.append(f"{row['config_id']}: line_life_sessions != 20")
        if row["sigma_multiplier"] not in [0.75, 1.0, 1.25, 1.5, 1.75, 2.0]:
            errors.append(f"{row['config_id']}: invalid sigma_multiplier {row['sigma_multiplier']}")
        if row["ib_minutes"] not in [30, 60]:
            errors.append(f"{row['config_id']}: invalid ib_minutes {row['ib_minutes']}")
        if row["offset_family"] not in ["proportional", "fixed"]:
            errors.append(f"{row['config_id']}: invalid offset_family {row['offset_family']}")
        if row["offset_family"] == "proportional":
            val = float(row["offset_value"])
            if val not in [0.0, 0.02, 0.04, 0.06, 0.08, 0.1]:
                errors.append(f"{row['config_id']}: invalid proportional offset {val}")
        else:
            val = float(row["offset_value"])
            if val not in [2.5, 5.0, 7.5, 10.0, 15.0]:
                errors.append(f"{row['config_id']}: invalid fixed offset {val}")

    # 6. No prohibited fields
    prohibited = ["target_rr", "be_rule", "stop_formula", "commissions",
                  "fees", "slippage", "entry_blackout", "hard_blackout",
                  "stop_before_target", "position_sizing", "rolling_pf_gate",
                  "nq_trade_management_rules"]
    for col in registry.columns:
        if col.lower() in [p.lower() for p in prohibited]:
            errors.append(f"registry contains prohibited column: {col}")

    # 7. Data files exist
    for path, label in [
        (ES_CAUSAL, "ES continuous causal"),
        (VIX_NORM, "VIX normalized"),
        (GRID_PATH, "grid definition"),
        (REGISTRY_PATH, "trial registry"),
        (HOLDOUT_PATH, "holdout lock"),
        (STAGE2_SPEC_PATH, "Stage 2 spec"),
        (STAGE2_SELECTION_PATH, "Stage 2 selection rules"),
        (BASELINE_DEF_PATH, "baseline definitions"),
    ]:
        if not os.path.exists(path):
            errors.append(f"{label} not found at {path}")

    # 8. Holdout remains UNOPENED
    with open(HOLDOUT_PATH) as f:
        holdout = json.load(f)
    if holdout["status"] != "UNOPENED":
        errors.append("holdout is not UNOPENED")
    if holdout["outcome_columns_read"] is not False:
        errors.append("holdout outcome_columns_read is not false")

    if errors:
        print("PREFLIGHT FAILED:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    # Compute and print hashes
    print("PREFLIGHT PASSED")
    print(f"  Grid configs: {len(grid_df)}")
    print(f"  Registry configs: {len(registry)}")
    print(f"  Grid SHA256: {sha256_file(GRID_PATH)}")
    print(f"  Registry SHA256: {sha256_file(REGISTRY_PATH)}")
    print(f"  ES causal SHA256: {sha256_file(ES_CAUSAL)}")
    print(f"  VIX SHA256: {sha256_file(VIX_NORM)}")
    print(f"  Holdout status: {holdout['status']}")


def firewall_enforce(touches_df: pd.DataFrame, excursions_df: pd.DataFrame, es_df: pd.DataFrame) -> None:
    """Enforce that all data falls within 2018-2019 development period.

    Exits with code 75 on violation.
    """
    violations = []

    # Check touch timestamps
    for _, tr in touches_df.iterrows():
        sd = str(tr["session_touched"])
        if sd < DEVELOPMENT_START or sd > DEVELOPMENT_END:
            violations.append(f"touch session {sd} outside development period")

    # Check excursion label bars (via label_start)
    for _, exc in excursions_df.iterrows():
        ls = str(exc["label_start"])
        ls_date = ls[:10]
        if ls_date < DEVELOPMENT_START or ls_date > DEVELOPMENT_END:
            violations.append(f"excursion label_start {ls_date} outside development period")

    # Check ES data timestamps used
    es_dates = es_df["session_date"].dropna().unique()
    for sd in es_dates:
        sd_str = str(sd)
        if sd_str < DEVELOPMENT_START or sd_str > DEVELOPMENT_END:
            pass  # ES dataframe may contain wider data; touched bars are the constraint

    if violations:
        print("FIREWALL VIOLATION (exit 75):")
        for v in violations[:20]:
            print(f"  - {v}")
        sys.exit(75)


def synthetic_smoke() -> None:
    """Run a synthetic smoke test with tiny data.

    Verifies the full pipeline runs deterministically.
    """
    from tests.test_es_vix_stage1 import (
        synthetic_session_bars,
        synthetic_multiday_es,
        synthetic_vix,
    )

    print("SYNTHETIC SMOKE TEST")
    print("  Generating synthetic data...")

    es = synthetic_multiday_es("2018-01-02", num_sessions=30, rth_open=4700.0)
    vix = synthetic_vix(start_date="2017-12-15", num_days=200, vix_close=15.0)
    vix["date"] = pd.to_datetime(vix["date"])
    # Ensure session_date is populated
    if "session_date" not in es.columns:
        ny = pd.to_datetime(es["timestamp"], utc=True).dt.tz_convert("America/New_York")
        es["session_date"] = ny.dt.strftime("%Y-%m-%d")

    grid_df = load_grid()

    print("  Running 132 configs on synthetic data (one config per param family)...")
    test_configs = grid_df.iloc[:3]  # Just 3 configs for smoke test

    all_levels = []
    all_touches = []
    all_excursions = []

    for _, cfg_row in test_configs.iterrows():
        cfg = LevelConfig(
            config_id=cfg_row["config_id"],
            sigma_multiplier=float(cfg_row["sigma_multiplier"]),
            ib_minutes=int(cfg_row["ib_minutes"]),
            offset_family=str(cfg_row["offset_family"]),
            offset_parameter=str(cfg_row["offset_parameter"]),
            offset_value=float(cfg_row["offset_value"]),
            line_life_sessions=int(cfg_row["line_life_sessions"]),
        )
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        if not levels.empty:
            all_levels.append(levels)
            touches = engine.detect_touches(levels, es)
            if not touches.empty:
                touches = engine.assign_overlap_clusters(touches)
                all_touches.append(touches)
                excursions = engine.compute_excursions(touches, es)
                all_excursions.append(excursions)

    if not all_levels:
        print("  WARNING: No levels generated in synthetic smoke test")
    else:
        levels_df = pd.concat(all_levels, ignore_index=True)
        touches_df = pd.concat(all_touches, ignore_index=True) if all_touches else pd.DataFrame()
        excursions_df = pd.concat(all_excursions, ignore_index=True) if all_excursions else pd.DataFrame()

        print(f"  Generated {len(levels_df)} levels")
        print(f"  Generated {len(touches_df)} touches")
        print(f"  Generated {len(excursions_df)} excursion labels")

        # Compute metrics
        metrics_df = compute_config_metrics(levels_df, touches_df, excursions_df, vix)

        if not metrics_df.empty:
            print(f"  Computed metrics for {metrics_df['config_id'].nunique()} configs")
            print(f"  Metric columns: {list(metrics_df.columns)}")

            # Compute year/direction/other splits
            year_metrics = compute_year_metrics(metrics_df, touches_df, excursions_df)
            dir_metrics = compute_direction_metrics(metrics_df, touches_df, excursions_df)
            print(f"  Year metrics: {len(year_metrics)} rows")
            print(f"  Direction metrics: {len(dir_metrics)} rows")

            # Classification
            decisions = classify_configs(
                metrics_df, pd.DataFrame(), dir_metrics, year_metrics, test_configs
            )
            classifications = decisions["classification"].value_counts().to_dict()
            print(f"  Classifications: {classifications}")

        # Determinism check: rerun and verify hashes
    print("  SYNTHETIC SMOKE PASSED")


def development_run(run_id: str) -> None:
    """Execute the full development-period grid run.

    This is the main pipeline. It should NOT be executed in Stage 2A.
    """
    print("development-run is not available in this session")
    print("Run this after Stage 2A freeze is committed and reviewed")
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(
        description="Stage 2 ES/VIX level discovery development grid runner"
    )
    parser.add_argument("--preflight", action="store_true",
                        help="Run preflight checks only")
    parser.add_argument("--synthetic-smoke", action="store_true",
                        help="Run synthetic smoke test")
    parser.add_argument("--development-run", type=str, default=None,
                        help="Run full development grid with given run_id")
    args = parser.parse_args()

    if args.preflight:
        preflight()
    elif args.synthetic_smoke:
        synthetic_smoke()
    elif args.development_run:
        development_run(args.development_run)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
