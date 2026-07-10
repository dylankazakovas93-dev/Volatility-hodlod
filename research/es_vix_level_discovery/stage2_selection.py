"""Stage 2: Frozen development elimination and survivor classification.

Uses Pareto-frontier analysis across multiple dimensions.
Classification labels: PASS, FAIL, INCONCLUSIVE_LOW_POWER.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

MIN_TOUCHES = 100
MIN_LONG = 30
MIN_SHORT = 30
MIN_SESSIONS = 40
SURVIVOR_CAP = 36


def classify_power(
    metrics_df: pd.DataFrame,
) -> pd.Series:
    """Return 'INCONCLUSIVE_LOW_POWER' for configs below minimum thresholds.

    Returns a Series indexed by config_id with power status.
    """
    power = {}
    for cfg_id in metrics_df["config_id"].unique():
        cfg_metrics = metrics_df[metrics_df["config_id"] == cfg_id]
        primary = cfg_metrics[cfg_metrics["horizon"].isin(["60m", "120m"])]
        if primary.empty:
            power[cfg_id] = "INCONCLUSIVE_LOW_POWER"
            continue

        max_touches = primary["valid_complete_labels"].max()
        long_count = primary["long_count"].max() if "long_count" in primary.columns else 0
        short_count = primary["short_count"].max() if "short_count" in primary.columns else 0
        max_sessions = primary["unique_sessions"].max() if "unique_sessions" in primary.columns else 0

        if (max_touches < MIN_TOUCHES
                or long_count < MIN_LONG
                or short_count < MIN_SHORT
                or max_sessions < MIN_SESSIONS):
            power[cfg_id] = "INCONCLUSIVE_LOW_POWER"
        else:
            power[cfg_id] = "PENDING"
    return pd.Series(power, name="power_status")


def _is_dominated(
    cfg_id: str,
    metrics_df: pd.DataFrame,
    horizon: str,
    pareto_dims: dict,
) -> bool:
    """Check if a config is clearly dominated on given pareto dimensions.

    pareto_dims: {metric_name: higher_is_better}
    Returns True if another config is at least as good on all dims and
    strictly better on at least one.
    """
    cfg_row = metrics_df[
        (metrics_df["config_id"] == cfg_id)
        & (metrics_df["horizon"] == horizon)
    ]
    if cfg_row.empty:
        return True
    cfg_row = cfg_row.iloc[0]

    others = metrics_df[
        (metrics_df["config_id"] != cfg_id)
        & (metrics_df["horizon"] == horizon)
    ]
    for _, other in others.iterrows():
        better_or_equal = True
        strictly_better = False
        for metric, higher_better in pareto_dims.items():
            cv = cfg_row.get(metric)
            ov = other.get(metric)
            if cv is None or ov is None:
                if cv is None and ov is not None:
                    better_or_equal = False
                    break
                continue
            if higher_better:
                if ov < cv:
                    better_or_equal = False
                    break
                if ov > cv:
                    strictly_better = True
            else:
                if ov > cv:
                    better_or_equal = False
                    break
                if ov < cv:
                    strictly_better = True
        if better_or_equal and strictly_better:
            return True
    return False


def _check_baseline_lift(
    cfg_id: str,
    baseline_df: pd.DataFrame,
) -> bool:
    """Check if baseline lift is nonpositive at both primary horizons.

    Returns True if FAIL condition applies.
    """
    metrics_to_check = [
        "median_mfe_points",
        "mean_directional_return_over_sigma",
    ]
    for horizon in ["60m", "120m"]:
        any_positive = False
        for metric in metrics_to_check:
            rows = baseline_df[
                (baseline_df["config_id"] == cfg_id)
                & (baseline_df["horizon"] == horizon)
                & (baseline_df["metric"] == metric)
            ]
            if not rows.empty:
                lift = rows["baseline_lift"].iloc[0]
                if lift is not None and lift > 0:
                    any_positive = True
        if any_positive:
            return False
    return True


def _check_one_direction(
    cfg_id: str,
    direction_metrics: pd.DataFrame,
) -> bool:
    """Check if nearly all support comes from one direction.

    Returns True if FAIL (e.g. >90% from one direction).
    """
    dir_df = direction_metrics[
        (direction_metrics["config_id"] == cfg_id)
        & (direction_metrics["horizon"].isin(["60m", "120m"]))
    ]
    if dir_df.empty:
        return False
    for horizon in ["60m", "120m"]:
        h = dir_df[dir_df["horizon"] == horizon]
        if h.empty:
            continue
        total = h["touch_count"].sum()
        if total == 0:
            continue
        long_share = h[h["direction"] == "LONG"]["touch_count"].sum() / total
        short_share = h[h["direction"] == "SHORT"]["touch_count"].sum() / total
        if long_share > 0.95 or short_share > 0.95:
            return True
    return False


def _check_temporal_clustering(
    cfg_id: str,
    year_metrics: pd.DataFrame,
) -> bool:
    """Check if nearly all support comes from one year."""
    yr = year_metrics[
        (year_metrics["config_id"] == cfg_id)
        & (year_metrics["horizon"].isin(["60m", "120m"]))
    ]
    if yr.empty:
        return False
    total = yr["touch_count"].sum()
    if total == 0:
        return False
    for _, row in yr.iterrows():
        share = row["touch_count"] / total
        if share > 0.95:
            return True
    return False


def _check_isolated_spike(
    cfg_id: str,
    metrics_df: pd.DataFrame,
    grid_df: pd.DataFrame,
) -> bool:
    """Check if it's an isolated parameter spike without neighbour support."""
    for horizon in ["60m", "120m"]:
        cfg_row = metrics_df[
            (metrics_df["config_id"] == cfg_id)
            & (metrics_df["horizon"] == horizon)
        ]
        if cfg_row.empty:
            continue
        cfg_mfe = cfg_row["median_mfe_points"].iloc[0]
        if cfg_mfe is None:
            continue

        # Get neighbours
        cfg_def = grid_df[grid_df["config_id"] == cfg_id]
        if cfg_def.empty:
            continue

        # Find neighbours (differ in exactly one parameter)
        all_others = grid_df[grid_df["config_id"] != cfg_id]
        neighbours = []
        for _, other in all_others.iterrows():
            diffs = 0
            if cfg_def["sigma_multiplier"].iloc[0] != other["sigma_multiplier"]:
                diffs += 1
            if cfg_def["ib_minutes"].iloc[0] != other["ib_minutes"]:
                diffs += 1
            if cfg_def["offset_family"].iloc[0] != other["offset_family"]:
                diffs += 1
            if cfg_def["offset_value"].iloc[0] != other["offset_value"]:
                diffs += 1
            if diffs == 1:
                neighbours.append(other["config_id"])

        if len(neighbours) < 2:
            continue

        neigh_metrics = metrics_df[
            (metrics_df["config_id"].isin(neighbours))
            & (metrics_df["horizon"] == horizon)
        ]
        neigh_mfe = neigh_metrics["median_mfe_points"].dropna()
        if neigh_mfe.empty:
            continue

        # If cfg_mfe is >2x the mean of neighbours, it's a spike
        if cfg_mfe > 2.0 * neigh_mfe.mean():
            return True
    return False


def classify_configs(
    metrics_df: pd.DataFrame,
    baseline_df: pd.DataFrame,
    direction_metrics: pd.DataFrame,
    year_metrics: pd.DataFrame,
    grid_df: pd.DataFrame,
    survivor_cap: int = SURVIVOR_CAP,
) -> pd.DataFrame:
    """Apply frozen development classification rules.

    Returns DataFrame with columns: config_id, classification, reasons.
    """
    power_status = classify_power(metrics_df)

    pareto_dims = {
        "median_mfe_points": True,
        "median_mae_points": False,
        "mean_directional_return_over_sigma": True,
        "positive_directional_return_rate": True,
    }

    decisions = []
    for cfg_id in sorted(metrics_df["config_id"].unique()):
        reasons = []

        if power_status.get(cfg_id) == "INCONCLUSIVE_LOW_POWER":
            decisions.append({
                "config_id": cfg_id,
                "classification": "INCONCLUSIVE_LOW_POWER",
                "reasons": "below_minimum_power_thresholds",
            })
            continue

        fail = False

        # Check baseline lift
        if not baseline_df.empty and _check_baseline_lift(cfg_id, baseline_df):
            fail = True
            reasons.append("baseline_lift_nonpositive_both_horizons")

        if not fail:
            # Check one-direction domination
            if not direction_metrics.empty and _check_one_direction(cfg_id, direction_metrics):
                fail = True
                reasons.append("one_direction_dominated")

        if not fail:
            # Check temporal clustering
            if not year_metrics.empty and _check_temporal_clustering(cfg_id, year_metrics):
                fail = True
                reasons.append("temporal_clustering_one_year")

        if not fail:
            # Check isolated spike
            if not grid_df.empty and _check_isolated_spike(cfg_id, metrics_df, grid_df):
                fail = True
                reasons.append("isolated_parameter_spike")

        if not fail:
            # Pareto dominance check
            for horizon in ["60m", "120m"]:
                if _is_dominated(cfg_id, metrics_df, horizon, pareto_dims):
                    fail = True
                    reasons.append(f"dominated_on_{horizon}")
                    break

        if fail:
            decisions.append({
                "config_id": cfg_id,
                "classification": "FAIL",
                "reasons": "; ".join(reasons),
            })
        else:
            decisions.append({
                "config_id": cfg_id,
                "classification": "PASS",
                "reasons": "",
            })

    result = pd.DataFrame(decisions)

    # Apply survivor cap
    passed = result[result["classification"] == "PASS"]
    if len(passed) > survivor_cap:
        excess_ids = passed["config_id"].iloc[survivor_cap:].tolist()
        result.loc[result["config_id"].isin(excess_ids), "classification"] = "FAIL"
        result.loc[result["config_id"].isin(excess_ids), "reasons"] = "excluded_by_survivor_cap"

    return result


def compute_median_ranks(
    metrics_df: pd.DataFrame,
    horizon: str = "60m",
) -> pd.DataFrame:
    """Compute median ranks across locked primary metrics as supporting summary.

    Lower rank is better. Ranks are averaged across selected metrics.
    """
    h_metrics = metrics_df[metrics_df["horizon"] == horizon].copy()
    if h_metrics.empty:
        return pd.DataFrame(columns=["config_id", "median_rank"])

    rank_metrics = [
        "median_mfe_points",
        "mean_directional_return_over_sigma",
        "positive_directional_return_rate",
    ]
    rank_dfs = []
    for metric in rank_metrics:
        if metric not in h_metrics.columns:
            continue
        ranked = h_metrics[["config_id", metric]].dropna().copy()
        ranked["rank"] = ranked[metric].rank(ascending=False)
        rank_dfs.append(ranked[["config_id", "rank"]].set_index("config_id"))

    if not rank_dfs:
        return pd.DataFrame(columns=["config_id", "median_rank"])

    combined = pd.concat(rank_dfs, axis=1)
    combined["median_rank"] = combined.median(axis=1)
    result = combined.reset_index()[["config_id", "median_rank"]].sort_values("median_rank")
    return result
