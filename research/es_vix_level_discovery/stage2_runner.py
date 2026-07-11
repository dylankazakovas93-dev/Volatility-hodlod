#!/usr/bin/env python3
"""Stage 2: Deterministic ES/VIX level discovery development-grid runner.

Usage:
    python research/es_vix_level_discovery/stage2_runner.py --preflight
    python research/es_vix_level_discovery/stage2_runner.py --synthetic-smoke
    python research/es_vix_level_discovery/stage2_runner.py \\
        --development-run <run_id> --confirm-development-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys

import numpy as np
import pandas as pd

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT_CANDIDATE = os.path.dirname(os.path.dirname(_THIS_DIR))
if _REPO_ROOT_CANDIDATE not in sys.path:
    sys.path.insert(0, _REPO_ROOT_CANDIDATE)

from research.es_vix_level_discovery.stage1_engine import (
    VIXLevelEngine,
    LevelConfig,
    _rth_bars,
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
    classify_power,
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
    errors = []
    grid_df = load_grid()
    if len(grid_df) != 132:
        errors.append(f"grid has {len(grid_df)} configs, expected 132")
    registry = load_registry()
    if len(registry) != 132:
        errors.append(f"registry has {len(registry)} configs, expected 132")
    if not registry["config_id"].is_unique:
        errors.append("registry has duplicate config_ids")
    grid_ids = set(grid_df["config_id"])
    reg_ids = set(registry["config_id"])
    if grid_ids != reg_ids:
        errors.append(f"grid/registry mismatch: {grid_ids ^ reg_ids}")
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
    prohibited = ["target_rr", "be_rule", "stop_formula", "commissions",
                  "fees", "slippage", "entry_blackout", "hard_blackout",
                  "stop_before_target", "position_sizing", "rolling_pf_gate",
                  "nq_trade_management_rules"]
    for col in registry.columns:
        if col.lower() in [p.lower() for p in prohibited]:
            errors.append(f"registry contains prohibited column: {col}")
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
    print("PREFLIGHT PASSED")
    print(f"  Grid configs: {len(grid_df)}")
    print(f"  Registry configs: {len(registry)}")
    print(f"  Grid SHA256: {sha256_file(GRID_PATH)}")
    print(f"  Registry SHA256: {sha256_file(REGISTRY_PATH)}")
    print(f"  ES causal SHA256: {sha256_file(ES_CAUSAL)}")
    print(f"  VIX SHA256: {sha256_file(VIX_NORM)}")
    print(f"  Holdout status: {holdout['status']}")


# ── Firewall ─────────────────────────────────────────────────────────

_FIREWALL_VIOLATIONS: list[str] = []


def _fw_check(val: str, label: str) -> None:
    """Check a single dated value against the development firewall."""
    d = str(val)[:10]
    if d < DEVELOPMENT_START or d > DEVELOPMENT_END:
        _FIREWALL_VIOLATIONS.append(f"{label}={d} outside {DEVELOPMENT_START}-{DEVELOPMENT_END}")


def firewall_enforce_full(
    levels_df: pd.DataFrame | None,
    touches_df: pd.DataFrame | None,
    excursions_df: pd.DataFrame | None,
    es_df: pd.DataFrame | None,
    baseline_detail: pd.DataFrame | None = None,
) -> None:
    """Comprehensive firewall.  Exits with code 75 on any violation.

    Inspects every dated field in every row of every dataframe.
    """
    _FIREWALL_VIOLATIONS.clear()

    # Level session and creation timestamps
    if levels_df is not None and not levels_df.empty:
        for _, row in levels_df.iterrows():
            _fw_check(row["session_date"], "level_session")
            _fw_check(row["created_at"], "level_created_at")
            if "first_eligible_at" in levels_df.columns:
                _fw_check(row["first_eligible_at"], "level_first_eligible_at")

    # Touch timestamps
    if touches_df is not None and not touches_df.empty:
        for _, row in touches_df.iterrows():
            _fw_check(row["session_touched"], "touch_session")
            _fw_check(row["touch_bar_timestamp"], "touch_bar")
            if "session_created" in touches_df.columns:
                _fw_check(row["session_created"], "touch_session_created")

    # Excursion label timestamps
    if excursions_df is not None and not excursions_df.empty:
        for _, row in excursions_df.iterrows():
            _fw_check(row["label_start"], "label_start")
            _fw_check(row["requested_end_exclusive"], "requested_end_exclusive")
            if row.get("actual_last_bar") is not None:
                _fw_check(row["actual_last_bar"], "actual_last_bar")

    # ES data session dates used for touch / label
    if es_df is not None and not es_df.empty:
        rth = _rth_bars(es_df)
        for sd in rth["session_date"].unique():
            if sd < DEVELOPMENT_START or sd > DEVELOPMENT_END:
                _FIREWALL_VIOLATIONS.append(f"ES_session_date={sd} outside development period")

    # Baseline random timestamps
    if baseline_detail is not None and not baseline_detail.empty:
        for _, row in baseline_detail.iterrows():
            _fw_check(row["random_timestamp"], "baseline_random_ts")

    if _FIREWALL_VIOLATIONS:
        print("FIREWALL VIOLATION (exit 75):")
        for v in _FIREWALL_VIOLATIONS[:50]:
            print(f"  - {v}")
        sys.exit(75)


# ── Synthetic smoke ──────────────────────────────────────────────────

def synthetic_smoke() -> None:
    from tests.test_es_vix_stage1 import (
        synthetic_session_bars,
        synthetic_multiday_es,
        synthetic_vix,
    )

    print("SYNTHETIC SMOKE TEST")
    es = synthetic_multiday_es("2018-01-02", num_sessions=30, rth_open=4700.0)
    vix = synthetic_vix(start_date="2017-12-15", num_days=200, vix_close=15.0)
    vix["date"] = pd.to_datetime(vix["date"])
    if "session_date" not in es.columns:
        ny = pd.to_datetime(es["timestamp"], utc=True).dt.tz_convert("America/New_York")
        es["session_date"] = ny.dt.strftime("%Y-%m-%d")

    grid_df = load_grid()
    test_configs = grid_df.iloc[:3]

    es_filtered = es[es["session_date"].between("2018-01-01", "2019-12-31")].copy()

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
        levels = engine.generate_levels(es_filtered, vix)
        if not levels.empty:
            all_levels.append(levels)
            touches = engine.detect_touches(levels, es_filtered)
            if not touches.empty:
                touches = engine.assign_overlap_clusters(touches)
                all_touches.append(touches)
                excursions = engine.compute_excursions(touches, es_filtered)
                all_excursions.append(excursions)

    if all_levels:
        levels_df = pd.concat(all_levels, ignore_index=True)
        touches_df = pd.concat(all_touches, ignore_index=True) if all_touches else pd.DataFrame()
        excursions_df = pd.concat(all_excursions, ignore_index=True) if all_excursions else pd.DataFrame()
        firewall_enforce_full(levels_df, touches_df, excursions_df, es_filtered)
        print(f"  Levels: {len(levels_df)}, Touches: {len(touches_df)}, Excursions: {len(excursions_df)}")
        metrics_df = compute_config_metrics(levels_df, touches_df, excursions_df, vix)
        print(f"  Metrics computed for {metrics_df['config_id'].nunique() if not metrics_df.empty else 0} configs")
        decisions = classify_configs(
            metrics_df, pd.DataFrame(), pd.DataFrame(),
            pd.DataFrame(), test_configs
        )
        print(f"  Classifications: {decisions['classification'].value_counts().to_dict() if not decisions.empty else {}}")
    else:
        print("  WARNING: No levels generated")
    print("  SYNTHETIC SMOKE PASSED")


# ── Development run ──────────────────────────────────────────────────

def development_run(run_id: str) -> None:
    """Execute the full development-period grid run."""
    print(f"DEVELOPMENT RUN: {run_id}")

    run_dir = os.path.join(RUNS_DIR, run_id)
    os.makedirs(run_dir, exist_ok=True)

    # 1. Load data
    print("  Loading data...")
    es_raw = pd.read_csv(ES_CAUSAL)
    vix = pd.read_csv(VIX_NORM, parse_dates=["date"])
    vix["date"] = pd.to_datetime(vix["date"])

    # 2. Filter ES to 2018-01-01 through 2019-12-31
    es = es_raw[es_raw["session_date"].between("2018-01-01", "2019-12-31")].copy()
    print(f"  ES filtered: {len(es)} rows ({es['session_date'].min()} to {es['session_date'].max()})")

    grid_df = load_grid()
    registry = load_registry()
    assert len(grid_df) == 132
    assert len(registry) == 132
    assert set(grid_df["config_id"]) == set(registry["config_id"])

    # 3. Run all configs
    print("  Running 132 configurations through Stage 1...")
    all_levels = []
    all_touches = []
    all_excursions = []

    for _, cfg_row in grid_df.iterrows():
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

    levels_df = pd.concat(all_levels, ignore_index=True) if all_levels else pd.DataFrame()
    touches_df = pd.concat(all_touches, ignore_index=True) if all_touches else pd.DataFrame()
    excursions_df = pd.concat(all_excursions, ignore_index=True) if all_excursions else pd.DataFrame()

    print(f"  Levels: {len(levels_df)}, Touches: {len(touches_df)}, Excursions: {len(excursions_df)}")

    # 4. Firewall
    firewall_enforce_full(levels_df, touches_df, excursions_df, es)

    # 5. Compute metrics
    print("  Computing metrics...")
    metrics_df = compute_config_metrics(levels_df, touches_df, excursions_df, vix)
    year_metrics = compute_year_metrics(metrics_df, touches_df, excursions_df)
    dir_metrics = compute_direction_metrics(metrics_df, touches_df, excursions_df)
    monthly_metrics = compute_monthly_metrics(touches_df, excursions_df)
    vix_regime = compute_vix_regime_metrics(touches_df, vix)
    tod_metrics = compute_time_of_day_metrics(touches_df)
    offset_family_metrics = compute_offset_family_metrics(touches_df, levels_df)
    conc_metrics = compute_concentration_metrics(touches_df, excursions_df)
    neighbour_support = compute_neighbour_support(metrics_df, grid_df)

    # 6. Baseline
    print("  Building matched-random baseline...")
    baseline = build_baseline(
        touches_df, levels_df, es, vix,
        horizons=["60m", "120m"],
        n_resamples=N_RESAMPLES,
    )
    baseline_aggregated = baseline["aggregated"]
    baseline_summary = baseline["summary"]
    vix_decile_bounds = baseline["vix_decile_bounds"]

    # Firewall on baseline random timestamps
    baseline_detail = pd.DataFrame()  # We don't keep detail by default
    firewall_enforce_full(None, None, None, es)

    # Baseline lift
    baseline_lift_df = compute_baseline_lift(
        metrics_df, baseline_aggregated, horizons=["60m", "120m"]
    )

    # 7. Classification
    print("  Classifying configurations...")
    decisions = classify_configs(
        metrics_df=metrics_df,
        baseline_lift_df=baseline_lift_df,
        direction_metrics=dir_metrics,
        year_metrics=year_metrics,
        grid_df=grid_df,
        excursions_df=excursions_df,
        neighbour_support_df=neighbour_support,
        survivor_cap=SURVIVOR_CAP,
    )

    # 8. Write artifacts
    print("  Writing artifacts...")

    # MANIFEST.json
    manifest = {
        "run_id": run_id,
        "strategy": "es_vix_level_discovery",
        "stage": 2,
        "development_period": f"{DEVELOPMENT_START}_to_{DEVELOPMENT_END}",
        "n_configs": 132,
        "base_seed": BASE_SEED,
        "n_resamples": N_RESAMPLES,
        "vix_decile_bounds": vix_decile_bounds,
        "generated_at_utc": None,
        "file_hashes": {},
    }
    with open(os.path.join(run_dir, "MANIFEST.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    # CONFIG_RESULTS.csv
    csv_path = os.path.join(run_dir, "CONFIG_RESULTS.csv")
    metrics_df.to_csv(csv_path, index=False, float_format="%.10f")
    manifest["file_hashes"]["CONFIG_RESULTS.csv"] = sha256_file(csv_path)

    # YEAR_RESULTS.csv
    csv_path = os.path.join(run_dir, "YEAR_RESULTS.csv")
    year_metrics.to_csv(csv_path, index=False, float_format="%.10f")
    manifest["file_hashes"]["YEAR_RESULTS.csv"] = sha256_file(csv_path)

    # DIRECTION_RESULTS.csv
    csv_path = os.path.join(run_dir, "DIRECTION_RESULTS.csv")
    dir_metrics.to_csv(csv_path, index=False, float_format="%.10f")
    manifest["file_hashes"]["DIRECTION_RESULTS.csv"] = sha256_file(csv_path)

    # MONTH_RESULTS.csv
    csv_path = os.path.join(run_dir, "MONTH_RESULTS.csv")
    monthly_metrics.to_csv(csv_path, index=False, float_format="%.10f")
    manifest["file_hashes"]["MONTH_RESULTS.csv"] = sha256_file(csv_path)

    # VIX_REGIME_RESULTS.csv
    csv_path = os.path.join(run_dir, "VIX_REGIME_RESULTS.csv")
    vix_regime.to_csv(csv_path, index=False, float_format="%.10f")
    manifest["file_hashes"]["VIX_REGIME_RESULTS.csv"] = sha256_file(csv_path)

    # TIME_OF_DAY_RESULTS.csv
    csv_path = os.path.join(run_dir, "TIME_OF_DAY_RESULTS.csv")
    tod_metrics.to_csv(csv_path, index=False, float_format="%.10f")
    manifest["file_hashes"]["TIME_OF_DAY_RESULTS.csv"] = sha256_file(csv_path)

    # BASELINE_RESULTS.csv
    csv_path = os.path.join(run_dir, "BASELINE_RESULTS.csv")
    if not baseline_summary.empty:
        baseline_summary.to_csv(csv_path, index=False, float_format="%.10f")
    else:
        pd.DataFrame().to_csv(csv_path, index=False)
    manifest["file_hashes"]["BASELINE_RESULTS.csv"] = sha256_file(csv_path)

    # NEIGHBOURHOOD_RESULTS.csv
    csv_path = os.path.join(run_dir, "NEIGHBOURHOOD_RESULTS.csv")
    neighbour_support.to_csv(csv_path, index=False, float_format="%.10f")
    manifest["file_hashes"]["NEIGHBOURHOOD_RESULTS.csv"] = sha256_file(csv_path)

    # SURVIVOR_DECISIONS.csv
    csv_path = os.path.join(run_dir, "SURVIVOR_DECISIONS.csv")
    decisions.to_csv(csv_path, index=False, float_format="%.10f")
    manifest["file_hashes"]["SURVIVOR_DECISIONS.csv"] = sha256_file(csv_path)

    # REPORT.md
    report_path = os.path.join(run_dir, "REPORT.md")
    passed = len(decisions[decisions["classification"] == "PASS"]) if not decisions.empty else 0
    failed = len(decisions[decisions["classification"] == "FAIL"]) if not decisions.empty else 0
    low_power = len(decisions[decisions["classification"] == "INCONCLUSIVE_LOW_POWER"]) if not decisions.empty else 0
    with open(report_path, "w") as f:
        f.write(f"# Stage 2 Development Run: {run_id}\n\n")
        f.write(f"**Development period:** {DEVELOPMENT_START} to {DEVELOPMENT_END}\n\n")
        f.write(f"**Configurations:** 132\n")
        f.write(f"**Touches:** {len(touches_df)}\n")
        f.write(f"**Excursions:** {len(excursions_df)}\n\n")
        f.write(f"## Classification\n\n")
        f.write(f"- PASS: {passed}\n")
        f.write(f"- FAIL: {failed}\n")
        f.write(f"- INCONCLUSIVE_LOW_POWER: {low_power}\n\n")
        f.write(f"## Survivor Cap\n\n")
        f.write(f"Max survivors: {SURVIVOR_CAP}\n")
        f.write(f"Configs retained: {min(passed, SURVIVOR_CAP)}\n")
    manifest["file_hashes"]["REPORT.md"] = sha256_file(report_path)

    # OUTPUT_HASHES.sha256
    sha_path = os.path.join(run_dir, "OUTPUT_HASHES.sha256")
    with open(sha_path, "w") as f:
        for fname, h in sorted(manifest["file_hashes"].items()):
            f.write(f"{h}  {fname}\n")
    manifest["file_hashes"]["OUTPUT_HASHES.sha256"] = sha256_file(sha_path)

    # Rewrite manifest with hashes
    with open(os.path.join(run_dir, "MANIFEST.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"  Run complete: {run_dir}")
    print(f"  PASS: {passed}, FAIL: {failed}, LOW_POWER: {low_power}")


# ── Main ─────────────────────────────────────────────────────────────

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
    parser.add_argument("--confirm-development-only", action="store_true",
                        help="Confirmation flag required for development run")
    args = parser.parse_args()

    if args.preflight:
        preflight()
    elif args.synthetic_smoke:
        synthetic_smoke()
    elif args.development_run:
        if not args.confirm_development_only:
            print("ERROR: --confirm-development-only is required with --development-run")
            print("This prevents accidental execution of the real grid.")
            sys.exit(1)
        development_run(args.development_run)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
