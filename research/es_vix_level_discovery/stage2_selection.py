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

SIGMA_VALS = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
PCT_OFFSETS = [0.0, 0.02, 0.04, 0.06, 0.08, 0.1]
FIXED_OFFSETS = [2.5, 5.0, 7.5, 10.0, 15.0]


def _are_adjacent_cells(c1: dict, c2: dict) -> bool:
    """Return True if c2 is an immediately adjacent grid neighbour of c1.

    Adjacent means differing on exactly one axis, where the differing
    value is the immediate previous or next value in that axis's domain
    *and* the offset family is the same.
    """
    if c1["config_id"] == c2["config_id"]:
        return False
    if c1["offset_family"] != c2["offset_family"]:
        return False

    diffs = 0
    if c1["sigma_multiplier"] != c2["sigma_multiplier"]:
        try:
            i1 = SIGMA_VALS.index(c1["sigma_multiplier"])
            i2 = SIGMA_VALS.index(c2["sigma_multiplier"])
        except ValueError:
            return False
        if abs(i1 - i2) != 1:
            return False
        diffs += 1
    if c1["ib_minutes"] != c2["ib_minutes"]:
        diffs += 1
    if c1["offset_value"] != c2["offset_value"]:
        if c1["offset_family"] == "proportional":
            try:
                i1 = PCT_OFFSETS.index(c1["offset_value"])
                i2 = PCT_OFFSETS.index(c2["offset_value"])
            except ValueError:
                return False
            if abs(i1 - i2) != 1:
                return False
        else:
            try:
                i1 = FIXED_OFFSETS.index(c1["offset_value"])
                i2 = FIXED_OFFSETS.index(c2["offset_value"])
            except ValueError:
                return False
            if abs(i1 - i2) != 1:
                return False
        diffs += 1
    return diffs == 1


# ── Power / Pareto / Fail helpers ────────────────────────────────────

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
    baseline_lift_df: pd.DataFrame,
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
            rows = baseline_lift_df[
                (baseline_lift_df["config_id"] == cfg_id)
                & (baseline_lift_df["horizon"] == horizon)
                & (baseline_lift_df["metric"] == metric)
            ]
            if not rows.empty:
                lift = rows["percentage_lift"].iloc[0]
                if lift is not None and lift > 0:
                    any_positive = True
        if any_positive:
            return False
    return True


def _check_stability_year_direction(
    cfg_id: str,
    year_metrics: pd.DataFrame,
    direction_metrics: pd.DataFrame,
    excursions_df: pd.DataFrame,
) -> list[str]:
    """Check stability separately for 60m and 120m.

    Flags:
    - year count concentration >80%
    - direction count concentration >80%
    - positive-return contribution concentration >90% when the other
      year/direction has nonpositive mean return.
    """
    reasons = []
    if year_metrics.empty or "config_id" not in year_metrics.columns:
        return reasons
    for horizon in ["60m", "120m"]:
        yr = year_metrics[
            (year_metrics["config_id"] == cfg_id)
            & (year_metrics["horizon"] == horizon)
        ]
        if yr.empty:
            continue
        total = yr["touch_count"].sum()
        if total > 0:
            for _, row in yr.iterrows():
                share = row["touch_count"] / total
                if share > 0.80:
                    reasons.append(f"{horizon}_year_{row['year']}_concentration_{share:.2f}")

        # Positive-return contribution concentration by year
        yr_ret = year_metrics[
            (year_metrics["config_id"] == cfg_id)
            & (year_metrics["horizon"] == horizon)
        ]
        if not yr_ret.empty and "mean_directional_return_over_sigma" in yr_ret.columns:
            yr_ret_sorted = yr_ret.sort_values("mean_directional_return_over_sigma", ascending=False)
            if len(yr_ret_sorted) >= 2:
                top_yr = yr_ret_sorted.iloc[0]
                bottom_yr = yr_ret_sorted.iloc[-1]
                if top_yr["touch_count"] > 0 and total > 0:
                    pos_share = top_yr["touch_count"] / total
                    if pos_share > 0.90 and bottom_yr.get("mean_directional_return_over_sigma", 0) is not None:
                        if bottom_yr["mean_directional_return_over_sigma"] is not None and bottom_yr["mean_directional_return_over_sigma"] <= 0:
                            reasons.append(f"{horizon}_year_return_concentration_{top_yr['year']}")

        if direction_metrics.empty or "config_id" not in direction_metrics.columns:
            continue
        dr = direction_metrics[
            (direction_metrics["config_id"] == cfg_id)
            & (direction_metrics["horizon"] == horizon)
        ]
        dir_total = dr["touch_count"].sum() if not dr.empty else 0
        if dir_total > 0:
            for _, row in dr.iterrows():
                share = row["touch_count"] / dir_total
                if share > 0.80:
                    reasons.append(f"{horizon}_direction_{row['direction']}_concentration_{share:.2f}")

        # Positive-return contribution concentration by direction
        if not dr.empty and "mean_directional_return_over_sigma" in dr.columns:
            dr_sorted = dr.sort_values("mean_directional_return_over_sigma", ascending=False)
            if len(dr_sorted) >= 2:
                top_dir = dr_sorted.iloc[0]
                bottom_dir = dr_sorted.iloc[-1]
                if top_dir["touch_count"] > 0 and dir_total > 0:
                    pos_share = top_dir["touch_count"] / dir_total
                    if pos_share > 0.90 and bottom_dir.get("mean_directional_return_over_sigma", 0) is not None:
                        if bottom_dir["mean_directional_return_over_sigma"] is not None and bottom_dir["mean_directional_return_over_sigma"] <= 0:
                            reasons.append(f"{horizon}_direction_return_concentration_{top_dir['direction']}")
    return reasons


def _check_isolated_spike(
    cfg_id: str,
    metrics_df: pd.DataFrame,
    grid_df: pd.DataFrame,
) -> bool:
    """Check if it's an isolated parameter spike without neighbour support.

    Uses the immediately-adjacent neighbour definition.
    """
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

        cfg_def = grid_df[grid_df["config_id"] == cfg_id]
        if cfg_def.empty:
            continue

        # Find neighbours using adjacent-cell rule
        all_others = grid_df[grid_df["config_id"] != cfg_id]
        neighbours = []
        for _, other in all_others.iterrows():
            c1 = cfg_def.iloc[0].to_dict()
            c2 = other.to_dict()
            if _are_adjacent_cells(c1, c2):
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

        if cfg_mfe > 2.0 * neigh_mfe.mean():
            return True
    return False


# ── Ranking helpers ──────────────────────────────────────────────────

def _safe_rank(series: pd.Series, ascending: bool = True) -> pd.Series:
    """Rank a series, handling ties with average rank."""
    return series.rank(ascending=ascending, method="average")


def compute_median_ranks(
    metrics_df: pd.DataFrame,
    horizons: list[str] | None = None,
) -> pd.DataFrame:
    """Compute equal-weight median ranks across both primary horizons.

    For each horizon, ranks each metric, averages to get that horizon's
    rank, then equal-weights across horizons.

    Lower combined rank is better.
    """
    if horizons is None:
        horizons = ["60m", "120m"]

    rank_metrics = [
        "median_mfe_points",
        "mean_directional_return_over_sigma",
        "positive_directional_return_rate",
    ]

    horizon_ranks = {}
    for horizon in horizons:
        h_metrics = metrics_df[metrics_df["horizon"] == horizon].copy()
        if h_metrics.empty:
            continue
        rank_dfs = []
        for metric in rank_metrics:
            if metric not in h_metrics.columns:
                continue
            ranked = h_metrics[["config_id", metric]].dropna().copy()
            ranked["rank"] = ranked[metric].rank(ascending=False, method="average")
            rank_dfs.append(ranked[["config_id", "rank"]].set_index("config_id"))
        if not rank_dfs:
            continue
        combined = pd.concat(rank_dfs, axis=1)
        combined["median_rank"] = combined.median(axis=1)
        horizon_ranks[horizon] = combined["median_rank"]

    if not horizon_ranks:
        return pd.DataFrame(columns=["config_id", "combined_rank"])

    all_ranks = pd.DataFrame(horizon_ranks)
    all_ranks["combined_rank"] = all_ranks.mean(axis=1)
    result = all_ranks.reset_index().rename(columns={"index": "config_id"})
    result = result[["config_id", "combined_rank"]].sort_values("combined_rank")
    return result


def compute_stability_rank(
    stability_reasons: dict[str, list[str]],
) -> pd.DataFrame:
    """Rank configs by stability (fewer reasons = better)."""
    items = [(cid, len(reasons)) for cid, reasons in stability_reasons.items()]
    df = pd.DataFrame(items, columns=["config_id", "n_stability_issues"])
    df["stability_rank"] = _safe_rank(df["n_stability_issues"], ascending=True)
    return df[["config_id", "stability_rank"]]


def compute_neighbour_support_rank(
    neighbourhood_df: pd.DataFrame,
) -> pd.DataFrame:
    """Rank configs by neighbour support (higher mean neighbour count = better).

    Uses the mean across both primary horizons.
    """
    if neighbourhood_df.empty:
        return pd.DataFrame(columns=["config_id", "neighbour_support_rank"])
    avg = neighbourhood_df.groupby("config_id")["neighbour_count"].mean().reset_index()
    avg["neighbour_support_rank"] = _safe_rank(avg["neighbour_count"], ascending=False)
    return avg[["config_id", "neighbour_support_rank"]]


# ── Main classifier ──────────────────────────────────────────────────

def classify_configs(
    metrics_df: pd.DataFrame,
    baseline_lift_df: pd.DataFrame,
    direction_metrics: pd.DataFrame,
    year_metrics: pd.DataFrame,
    grid_df: pd.DataFrame,
    excursions_df: pd.DataFrame | None = None,
    neighbour_support_df: pd.DataFrame | None = None,
    survivor_cap: int = SURVIVOR_CAP,
) -> pd.DataFrame:
    """Apply frozen development classification rules.

    Returns DataFrame with columns: config_id, classification, reasons,
    and ranking columns for survivors.
    """
    power_status = classify_power(metrics_df)

    pareto_dims = {
        "median_mfe_points": True,
        "median_mae_points": False,
        "mean_directional_return_over_sigma": True,
        "positive_directional_return_rate": True,
    }

    decisions = []
    stability_reasons_map = {}

    for cfg_id in sorted(metrics_df["config_id"].unique()):
        reasons = []
        fail = False

        if power_status.get(cfg_id) == "INCONCLUSIVE_LOW_POWER":
            decisions.append({
                "config_id": cfg_id,
                "classification": "INCONCLUSIVE_LOW_POWER",
                "reasons": "below_minimum_power_thresholds",
            })
            stability_reasons_map[cfg_id] = []
            continue

        # Baseline lift fail
        if not baseline_lift_df.empty and _check_baseline_lift(cfg_id, baseline_lift_df):
            fail = True
            reasons.append("baseline_lift_nonpositive_both_horizons")

        # Stability checks (always computed for ranking, fail only on severe issues)
        _exc_df = excursions_df if excursions_df is not None else pd.DataFrame()
        _ym = year_metrics if not year_metrics.empty and "config_id" in year_metrics.columns else pd.DataFrame()
        _dm = direction_metrics if not direction_metrics.empty and "config_id" in direction_metrics.columns else pd.DataFrame()
        stability_reasons = _check_stability_year_direction(
            cfg_id, _ym, _dm, _exc_df
        )
        stability_reasons_map[cfg_id] = stability_reasons

        if not fail and stability_reasons:
            # Flag stability issues but don't auto-fail
            reasons.append("stability_issue: " + "; ".join(stability_reasons))

        # One-direction domination (severe)
        if not fail:
            if not direction_metrics.empty:
                yr = year_metrics[
                    (year_metrics["config_id"] == cfg_id)
                    & (year_metrics["horizon"].isin(["60m", "120m"]))
                ]
                dir_df = direction_metrics[
                    (direction_metrics["config_id"] == cfg_id)
                    & (direction_metrics["horizon"].isin(["60m", "120m"]))
                ]
                one_dir_fail = False
                for horizon in ["60m", "120m"]:
                    h = dir_df[dir_df["horizon"] == horizon]
                    total = h["touch_count"].sum()
                    if total > 0:
                        long_share = h[h["direction"] == "LONG"]["touch_count"].sum() / total
                        short_share = h[h["direction"] == "SHORT"]["touch_count"].sum() / total
                        if long_share > 0.95 or short_share > 0.95:
                            one_dir_fail = True
                if one_dir_fail:
                    fail = True
                    reasons.append("one_direction_dominated")

        # Temporal clustering (severe)
        if not fail:
            if not year_metrics.empty:
                yr = year_metrics[
                    (year_metrics["config_id"] == cfg_id)
                    & (year_metrics["horizon"].isin(["60m", "120m"]))
                ]
                total = yr["touch_count"].sum()
                temp_fail = False
                if total > 0:
                    for _, row in yr.iterrows():
                        if row["touch_count"] / total > 0.95:
                            temp_fail = True
                if temp_fail:
                    fail = True
                    reasons.append("temporal_clustering_one_year")

        # Isolated spike
        if not fail:
            if not grid_df.empty and _check_isolated_spike(cfg_id, metrics_df, grid_df):
                fail = True
                reasons.append("isolated_parameter_spike")

        # Pareto dominance (joint across both primary horizons)
        if not fail:
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
                "reasons": "; ".join(reasons),
            })

    result = pd.DataFrame(decisions)

    # Rank survivors
    passed_ids = result[result["classification"] == "PASS"]["config_id"].tolist()
    if len(passed_ids) > 0:
        passed_metrics = metrics_df[metrics_df["config_id"].isin(passed_ids)]

        # Combined rank from median ranks
        rank_df = compute_median_ranks(passed_metrics, horizons=["60m", "120m"])

        # Stability rank
        stab_ranks = compute_stability_rank(stability_reasons_map)
        rank_df = rank_df.merge(stab_ranks, on="config_id", how="left")
        rank_df["stability_rank"] = rank_df["stability_rank"].fillna(
            rank_df["stability_rank"].max() if not rank_df["stability_rank"].isna().all() else len(rank_df)
        )

        # Neighbour support rank
        if neighbour_support_df is not None and not neighbour_support_df.empty:
            neigh_ranks = compute_neighbour_support_rank(neighbour_support_df)
            rank_df = rank_df.merge(neigh_ranks, on="config_id", how="left")

        rank_df["neighbour_support_rank"] = rank_df.get("neighbour_support_rank", pd.Series(
            rank_df.index.max() + 1, index=rank_df.index
        ))
        if rank_df["neighbour_support_rank"].isna().all():
            rank_df["neighbour_support_rank"] = rank_df.index.max() + 1
        rank_df["neighbour_support_rank"] = rank_df["neighbour_support_rank"].fillna(
            rank_df["neighbour_support_rank"].max()
        )

        # Combined ranking: equal weight across combined_rank, stability_rank, neighbour_support_rank
        rank_cols = ["combined_rank", "stability_rank", "neighbour_support_rank"]
        available = [c for c in rank_cols if c in rank_df.columns]
        rank_df["final_rank"] = rank_df[available].mean(axis=1)
        rank_df = rank_df.sort_values("final_rank")

        # Apply survivor cap: keep at most strongest 36
        if len(rank_df) > survivor_cap:
            survive_ids = set(rank_df["config_id"].iloc[:survivor_cap])
            result.loc[
                (result["classification"] == "PASS")
                & (~result["config_id"].isin(survive_ids)),
                "classification"
            ] = "FAIL"
            result.loc[
                (result["classification"] == "FAIL")
                & (result["config_id"].isin(
                    set(passed_ids) - survive_ids
                )),
                "reasons"
            ] = "excluded_by_survivor_cap"

        # Attach ranks to result
        rank_map = rank_df.set_index("config_id")[["final_rank"]].to_dict()["final_rank"]
        result["rank"] = result["config_id"].map(rank_map)

    return result
