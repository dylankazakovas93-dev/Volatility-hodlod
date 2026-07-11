"""Stage 2: Deterministic metric calculation for ES/VIX level discovery.

All metrics are computed per configuration per horizon using only COMPLETE
labels unless otherwise specified.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

PRIMARY_HORIZONS = ["60m", "120m"]
SECONDARY_HORIZONS = ["15m", "30m", "RTH_REMAINDER"]
ALL_HORIZONS = PRIMARY_HORIZONS + SECONDARY_HORIZONS
FP_THRESHOLDS = [0.25, 0.50, 0.75, 1.00]


def _safe_median(series: pd.Series) -> Optional[float]:
    s = series.dropna()
    if s.empty:
        return None
    return float(np.median(s))


def _safe_mean(series: pd.Series) -> Optional[float]:
    s = series.dropna()
    if s.empty:
        return None
    return float(np.mean(s))


def _safe_quantile(series: pd.Series, q: float) -> Optional[float]:
    s = series.dropna()
    if s.empty:
        return None
    return float(np.quantile(s, q))


def _safe_count(series: pd.Series) -> int:
    return int(series.dropna().shape[0])


def compute_config_metrics(
    levels_df: pd.DataFrame,
    touches_df: pd.DataFrame,
    excursions_df: pd.DataFrame,
    vix_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute all locked metrics per configuration per horizon.

    Parameters
    ----------
    levels_df : pd.DataFrame
        Stage 1 level output for all configs.
    touches_df : pd.DataFrame
        Stage 1 touch output for all configs (with overlap_cluster_id).
    excursions_df : pd.DataFrame
        Stage 1 excursion output for all configs.
    vix_df : pd.DataFrame
        VIX daily data with 'date' and 'vix_close' columns (used for
        VIX-regime distribution).

    Returns
    -------
    pd.DataFrame with columns: config_id, horizon, and all metric columns.
    """
    config_ids = sorted(levels_df["config_id"].unique())
    all_rows = []

    for cfg_id in config_ids:
        cfg_levels = levels_df[levels_df["config_id"] == cfg_id]
        cfg_touches = touches_df[touches_df["config_id"] == cfg_id]
        cfg_exc = excursions_df[excursions_df["config_id"] == cfg_id]

        generated_levels = len(cfg_levels)
        physical_touches = len(cfg_touches)

        for horizon in ALL_HORIZONS:
            h_exc = cfg_exc[cfg_exc["horizon"] == horizon]

            complete = h_exc[h_exc["label_status"] == "COMPLETE"]
            incomplete = h_exc[h_exc["label_status"] == "INCOMPLETE"]

            valid_n = len(complete)
            incomplete_n = len(incomplete)

            # Counts
            long_touches = int(
                (cfg_touches["touch_direction"] == "LONG").sum()
            )
            short_touches = int(
                (cfg_touches["touch_direction"] == "SHORT").sum()
            )
            gap_through = int(cfg_touches["gap_through"].sum())

            ambiguous_fp = 0
            for thresh_name in ["fp_025_sigma", "fp_050_sigma", "fp_075_sigma", "fp_100_sigma"]:
                if thresh_name in complete.columns:
                    ambiguous_fp += int((complete[thresh_name] == "AMBIGUOUS").sum())

            unique_sessions = int(cfg_touches["session_touched"].nunique())

            overlap_cluster_ids = cfg_touches[
                cfg_touches["overlap_cluster_id"] > 0
            ]["overlap_cluster_id"]
            overlap_clusters = int(overlap_cluster_ids.nunique())

            # Overlap-adjusted effective n: treat each cluster as 1 observation
            if overlap_clusters > 0:
                non_overlap = int((cfg_touches["overlap_cluster_id"] == 0).sum())
                overlap_adj_n = non_overlap + overlap_clusters
            else:
                overlap_adj_n = valid_n

            # Excursion metrics (complete only)
            median_mfe = _safe_median(complete["mfe"])
            median_mae = _safe_median(complete["mae"])
            median_mfe_sigma = _safe_median(complete["mfe_sigma_ratio"])
            median_mae_sigma = _safe_median(complete["mae_sigma_ratio"])
            median_mfe_ibr = _safe_median(complete["mfe_ib_range_ratio"])
            median_mae_ibr = _safe_median(complete["mae_ib_range_ratio"])
            p75_mfe_sigma = _safe_quantile(complete["mfe_sigma_ratio"], 0.75)
            p90_mfe_sigma = _safe_quantile(complete["mfe_sigma_ratio"], 0.90)
            p75_mae_sigma = _safe_quantile(complete["mae_sigma_ratio"], 0.75)
            p90_mae_sigma = _safe_quantile(complete["mae_sigma_ratio"], 0.90)
            p95_mae_sigma = _safe_quantile(complete["mae_sigma_ratio"], 0.95)

            # Return metrics
            mean_dir_ret = _safe_mean(complete["directional_horizon_close_return_sigma"])
            median_dir_ret = _safe_median(complete["directional_horizon_close_return_sigma"])
            pos_ret_rate = None
            ret_vals = complete["directional_horizon_close_return_sigma"].dropna()
            if len(ret_vals) > 0:
                pos_ret_rate = float((ret_vals > 0).sum() / len(ret_vals))

            # First-passage rates
            fp_metrics = {}
            for thresh in FP_THRESHOLDS:
                col = f"fp_{thresh:.2f}_sigma".replace(".", "")
                if col not in complete.columns:
                    col = f"fp_{int(thresh*100):03d}_sigma"

                statuses = complete[col].dropna() if col in complete.columns else pd.Series(dtype=str)
                total = len(statuses)
                if total > 0:
                    fav = float((statuses == "FAVORABLE_FIRST").sum() / total)
                    adv = float((statuses == "ADVERSE_FIRST").sum() / total)
                    amb = float((statuses == "AMBIGUOUS").sum() / total)
                    none_r = float((statuses == "NOT_REACHED").sum() / total)
                else:
                    fav = adv = amb = none_r = None
                fp_metrics[f"p_favorable_first_{thresh:.2f}"] = fav
                fp_metrics[f"p_adverse_first_{thresh:.2f}"] = adv
                fp_metrics[f"p_ambiguous_{thresh:.2f}"] = amb
                fp_metrics[f"p_neither_reached_{thresh:.2f}"] = none_r

            # Ratio of medians
            ratio_of_medians = None
            if median_mfe is not None and median_mae is not None and median_mae != 0.0:
                ratio_of_medians = median_mfe / median_mae

            row = {
                "config_id": cfg_id,
                "horizon": horizon,
                "generated_levels": generated_levels,
                "physical_first_touches": physical_touches,
                "valid_complete_labels": valid_n,
                "incomplete_labels": incomplete_n,
                "long_count": long_touches,
                "short_count": short_touches,
                "gap_through_count": gap_through,
                "ambiguous_first_passage_count": ambiguous_fp,
                "unique_sessions": unique_sessions,
                "overlap_clusters": overlap_clusters,
                "overlap_adjusted_effective_n": overlap_adj_n,
                "median_mfe_points": median_mfe,
                "median_mae_points": median_mae,
                "median_mfe_over_sigma_day": median_mfe_sigma,
                "median_mae_over_sigma_day": median_mae_sigma,
                "median_mfe_over_ib_range": median_mfe_ibr,
                "median_mae_over_ib_range": median_mae_ibr,
                "p75_mfe_over_sigma_day": p75_mfe_sigma,
                "p90_mfe_over_sigma_day": p90_mfe_sigma,
                "p75_mae_over_sigma_day": p75_mae_sigma,
                "p90_mae_over_sigma_day": p90_mae_sigma,
                "p95_mae_over_sigma_day": p95_mae_sigma,
                "mean_directional_return_over_sigma": mean_dir_ret,
                "median_directional_return_over_sigma": median_dir_ret,
                "positive_directional_return_rate": pos_ret_rate,
                "mfe_mae_ratio_of_medians": ratio_of_medians,
            }
            row.update(fp_metrics)
            all_rows.append(row)

    if not all_rows:
        columns = [
            "config_id", "horizon", "generated_levels", "physical_first_touches",
            "valid_complete_labels", "incomplete_labels", "long_count",
            "short_count", "gap_through_count", "ambiguous_first_passage_count",
            "unique_sessions", "overlap_clusters", "overlap_adjusted_effective_n",
            "median_mfe_points", "median_mae_points",
            "median_mfe_over_sigma_day", "median_mae_over_sigma_day",
            "median_mfe_over_ib_range", "median_mae_over_ib_range",
            "p75_mfe_over_sigma_day", "p90_mfe_over_sigma_day",
            "p75_mae_over_sigma_day", "p90_mae_over_sigma_day",
            "p95_mae_over_sigma_day",
            "mean_directional_return_over_sigma",
            "median_directional_return_over_sigma",
            "positive_directional_return_rate",
            "mfe_mae_ratio_of_medians",
        ]
        for thresh in FP_THRESHOLDS:
            for label in ["p_favorable_first", "p_adverse_first",
                          "p_ambiguous", "p_neither_reached"]:
                columns.append(f"{label}_{thresh:.2f}")
        return pd.DataFrame(columns=columns)

    return pd.DataFrame(all_rows)


def compute_year_metrics(
    metrics_df: pd.DataFrame,
    touches_df: pd.DataFrame,
    excursions_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute year-split metrics (2018, 2019) per config per horizon."""
    rows = []
    for cfg_id in sorted(metrics_df["config_id"].unique()):
        for horizon in PRIMARY_HORIZONS:
            cfg_touches = touches_df[touches_df["config_id"] == cfg_id]
            cfg_exc = excursions_df[
                (excursions_df["config_id"] == cfg_id)
                & (excursions_df["horizon"] == horizon)
            ]
            for year_label, year_str in [("2018", "2018"), ("2019", "2019")]:
                year_touches = cfg_touches[
                    cfg_touches["session_touched"].str.startswith(year_str)
                ]
                touched_ids = set(year_touches["touch_id"])
                year_exc = cfg_exc[cfg_exc["touch_id"].isin(touched_ids)]
                complete = year_exc[year_exc["label_status"] == "COMPLETE"]
                rows.append({
                    "config_id": cfg_id,
                    "horizon": horizon,
                    "year": year_label,
                    "touch_count": len(year_touches),
                    "complete_label_count": len(complete),
                    "median_mfe_points": _safe_median(complete["mfe"]),
                    "median_mae_points": _safe_median(complete["mae"]),
                    "mean_directional_return_over_sigma": _safe_mean(
                        complete["directional_horizon_close_return_sigma"]
                    ),
                })
    return pd.DataFrame(rows)


def compute_direction_metrics(
    metrics_df: pd.DataFrame,
    touches_df: pd.DataFrame,
    excursions_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute direction-split metrics per config per horizon."""
    rows = []
    for cfg_id in sorted(metrics_df["config_id"].unique()):
        for horizon in PRIMARY_HORIZONS:
            cfg_exc = excursions_df[
                (excursions_df["config_id"] == cfg_id)
                & (excursions_df["horizon"] == horizon)
            ]
            for direction in ["LONG", "SHORT"]:
                dir_touch_ids = set(
                    touches_df[
                        (touches_df["config_id"] == cfg_id)
                        & (touches_df["touch_direction"] == direction)
                    ]["touch_id"]
                )
                dir_exc = cfg_exc[cfg_exc["touch_id"].isin(dir_touch_ids)]
                complete = dir_exc[dir_exc["label_status"] == "COMPLETE"]
                rows.append({
                    "config_id": cfg_id,
                    "horizon": horizon,
                    "direction": direction,
                    "touch_count": len(dir_touch_ids),
                    "complete_label_count": len(complete),
                    "median_mfe_points": _safe_median(complete["mfe"]),
                    "median_mae_points": _safe_median(complete["mae"]),
                    "mean_directional_return_over_sigma": _safe_mean(
                        complete["directional_horizon_close_return_sigma"]
                    ),
                })
    return pd.DataFrame(rows)


def compute_monthly_metrics(
    touches_df: pd.DataFrame,
    excursions_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute monthly touch/distribution metrics per config per horizon."""
    rows = []
    for cfg_id in sorted(touches_df["config_id"].unique()):
        cfg_touches = touches_df[touches_df["config_id"] == cfg_id]
        for horizon in PRIMARY_HORIZONS:
            cfg_exc = excursions_df[
                (excursions_df["config_id"] == cfg_id)
                & (excursions_df["horizon"] == horizon)
            ]
            complete = cfg_exc[cfg_exc["label_status"] == "COMPLETE"]
            for _, tr in cfg_touches.iterrows():
                sd = str(tr["session_touched"])
                month = sd[:7]
                rows.append({
                    "config_id": cfg_id,
                    "horizon": horizon,
                    "month": month,
                    "touch_id": tr["touch_id"],
                    "touch_direction": tr["touch_direction"],
                    "gap_through": tr["gap_through"],
                })
    if not rows:
        return pd.DataFrame(columns=[
            "config_id", "horizon", "month", "touch_count", "long_count", "short_count"
        ])
    df = pd.DataFrame(rows)
    grouped = df.groupby(["config_id", "horizon", "month"]).agg(
        touch_count=("touch_id", "count"),
        long_count=("touch_direction", lambda x: (x == "LONG").sum()),
        short_count=("touch_direction", lambda x: (x == "SHORT").sum()),
    ).reset_index()
    return grouped


def compute_vix_regime_metrics(
    touches_df: pd.DataFrame,
    vix_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute VIX-decile distribution per config.

    VIX decile boundaries computed from 2018-2019 development data.
    """
    vix_dev = vix_df[
        (vix_df["date"] >= "2018-01-01") & (vix_df["date"] <= "2019-12-31")
    ]
    vix_vals = vix_dev["vix_close"].dropna().values
    if len(vix_vals) < 10:
        decile_bounds = [float(np.quantile(vix_vals, i / 10)) for i in range(11)]
    else:
        decile_bounds = [float(np.quantile(vix_vals, i / 10)) for i in range(11)]
    decile_bounds[0] = -float("inf")
    decile_bounds[-1] = float("inf")

    def _vix_decile(vix_close_val):
        for i in range(10):
            if decile_bounds[i] <= vix_close_val < decile_bounds[i + 1]:
                return i + 1
        return 10

    rows = []
    for cfg_id in sorted(touches_df["config_id"].unique()):
        cfg_touches = touches_df[touches_df["config_id"] == cfg_id]
        for _, tr in cfg_touches.iterrows():
            vix_close = tr.get("sigma_day")  # sigma_day stored on touch
            rows.append({
                "config_id": cfg_id,
                "touch_id": tr["touch_id"],
                "vix_close": vix_close,
            })

    if not rows:
        return pd.DataFrame(columns=["config_id", "decile", "touch_count"])
    dist_df = pd.DataFrame(rows)
    dist_df["decile"] = dist_df["vix_close"].apply(
        lambda x: _vix_decile(x) if pd.notna(x) else None
    )
    grouped = dist_df.groupby(["config_id", "decile"]).size().reset_index(name="touch_count")
    return grouped


def compute_time_of_day_metrics(touches_df: pd.DataFrame) -> pd.DataFrame:
    """Compute time-of-day (30-min bucket) distribution per config."""
    rows = []
    for cfg_id in sorted(touches_df["config_id"].unique()):
        cfg_touches = touches_df[touches_df["config_id"] == cfg_id]
        for _, tr in cfg_touches.iterrows():
            ts = pd.Timestamp(tr["touch_bar_timestamp"])
            hour = ts.hour
            minute = ts.minute
            bucket_min = (minute // 30) * 30
            bucket = f"{hour:02d}:{bucket_min:02d}"
            rows.append({
                "config_id": cfg_id,
                "touch_id": tr["touch_id"],
                "tod_bucket": bucket,
            })
    if not rows:
        return pd.DataFrame(columns=["config_id", "tod_bucket", "touch_count"])
    df = pd.DataFrame(rows)
    grouped = df.groupby(["config_id", "tod_bucket"]).size().reset_index(name="touch_count")
    return grouped


def compute_offset_family_metrics(
    touches_df: pd.DataFrame, levels_df: pd.DataFrame
) -> pd.DataFrame:
    """Compute offset-family distribution per config."""
    level_offsets = levels_df[["config_id", "offset_family"]].drop_duplicates()
    merged = touches_df.merge(level_offsets, on="config_id", how="left")
    grouped = merged.groupby(["config_id", "offset_family"]).size().reset_index(name="touch_count")
    return grouped


def _are_adjacent_cells(c1: dict, c2: dict) -> bool:
    """Return True if c2 is an immediately adjacent grid neighbour of c1.

    Adjacent means differing on exactly one axis, where the differing
    value is the immediate previous or next value in that axis's domain
    *and* the offset family is the same (proportional vs fixed are never
    neighbours).
    """
    if c1["config_id"] == c2["config_id"]:
        return False
    if c1["offset_family"] != c2["offset_family"]:
        return False
    sigma_vals = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
    pct_offsets = [0.0, 0.02, 0.04, 0.06, 0.08, 0.1]
    fixed_offsets = [2.5, 5.0, 7.5, 10.0, 15.0]

    diffs = 0
    # sigma
    if c1["sigma_multiplier"] != c2["sigma_multiplier"]:
        try:
            i1 = sigma_vals.index(c1["sigma_multiplier"])
            i2 = sigma_vals.index(c2["sigma_multiplier"])
        except ValueError:
            return False
        if abs(i1 - i2) != 1:
            return False
        diffs += 1
    # ib_minutes
    if c1["ib_minutes"] != c2["ib_minutes"]:
        diffs += 1
    # offset_value (same family already checked)
    if c1["offset_value"] != c2["offset_value"]:
        if c1["offset_family"] == "proportional":
            try:
                i1 = pct_offsets.index(c1["offset_value"])
                i2 = pct_offsets.index(c2["offset_value"])
            except ValueError:
                return False
            if abs(i1 - i2) != 1:
                return False
        else:  # fixed
            try:
                i1 = fixed_offsets.index(c1["offset_value"])
                i2 = fixed_offsets.index(c2["offset_value"])
            except ValueError:
                return False
            if abs(i1 - i2) != 1:
                return False
        diffs += 1
    return diffs == 1


def compute_neighbour_support(
    metrics_df: pd.DataFrame,
    grid_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compute immediately-adjacent neighbour support for each config.

    A neighbour is an immediately adjacent grid cell: previous/next
    sigma, 30 vs 60 IB, previous/next offset within the same offset
    family.  Proportional and fixed families are never neighbours.
    """
    configs = grid_df.to_dict("records")
    neighbour_map = {}
    for i, c1 in enumerate(configs):
        neighbours = []
        for j, c2 in enumerate(configs):
            if _are_adjacent_cells(c1, c2):
                neighbours.append(c2["config_id"])
        neighbour_map[c1["config_id"]] = neighbours

    rows = []
    for cfg_id, neighbours in neighbour_map.items():
        for horizon in PRIMARY_HORIZONS:
            cfg_metrics = metrics_df[
                (metrics_df["config_id"] == cfg_id)
                & (metrics_df["horizon"] == horizon)
            ]
            neigh_metrics = metrics_df[
                (metrics_df["config_id"].isin(neighbours))
                & (metrics_df["horizon"] == horizon)
            ]
            rows.append({
                "config_id": cfg_id,
                "horizon": horizon,
                "neighbour_count": len(neighbours),
                "neighbour_mean_median_mfe": _safe_mean(
                    neigh_metrics["median_mfe_points"]
                ),
                "neighbour_mean_median_mae": _safe_mean(
                    neigh_metrics["median_mae_points"]
                ),
                "neighbour_mean_median_dir_return": _safe_mean(
                    neigh_metrics["mean_directional_return_over_sigma"]
                ),
            })
    return pd.DataFrame(rows)


def compute_concentration_metrics(
    touches_df: pd.DataFrame,
    excursions_df: pd.DataFrame,
) -> pd.DataFrame:
    """Concentration by best 5% of sessions and by best month."""
    rows = []
    for cfg_id in sorted(touches_df["config_id"].unique()):
        for horizon in PRIMARY_HORIZONS:
            cfg_touches = touches_df[touches_df["config_id"] == cfg_id]
            cfg_exc = excursions_df[
                (excursions_df["config_id"] == cfg_id)
                & (excursions_df["horizon"] == horizon)
            ]
            complete = cfg_exc[cfg_exc["label_status"] == "COMPLETE"]
            if complete.empty:
                continue

            # By session
            by_session = complete.groupby(
                complete["touch_id"].map(
                    lambda tid: cfg_touches[
                        cfg_touches["touch_id"] == tid
                    ]["session_touched"].iloc[0]
                    if tid in set(cfg_touches["touch_id"]) else None
                )
            )["directional_horizon_close_return_sigma"].mean()
            by_session = by_session.dropna()
            total_sessions = len(by_session)
            if total_sessions > 0:
                n_top = max(1, int(math.ceil(total_sessions * 0.05)))
                top_sessions = by_session.nlargest(n_top)
                concentration_session = float(top_sessions.sum() / by_session.sum()) if by_session.sum() != 0 else None
            else:
                concentration_session = None

            # By month
            monthly_returns = []
            for _, exc_row in complete.iterrows():
                tid = exc_row["touch_id"]
                touch_row = cfg_touches[cfg_touches["touch_id"] == tid]
                if touch_row.empty:
                    continue
                month = str(touch_row["session_touched"].iloc[0])[:7]
                monthly_returns.append({
                    "month": month,
                    "ret": exc_row["directional_horizon_close_return_sigma"],
                })
            if monthly_returns:
                mdf = pd.DataFrame(monthly_returns).dropna()
                if not mdf.empty:
                    by_month = mdf.groupby("month")["ret"].mean()
                    top_month = by_month.nlargest(1)
                    concentration_month = float(top_month.iloc[0] / by_month.sum()) if by_month.sum() != 0 else None
                else:
                    concentration_month = None
            else:
                concentration_month = None

            rows.append({
                "config_id": cfg_id,
                "horizon": horizon,
                "concentration_best_5pct_sessions": concentration_session,
                "concentration_best_month": concentration_month,
            })
    return pd.DataFrame(rows)
