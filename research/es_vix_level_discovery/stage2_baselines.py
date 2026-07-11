"""Stage 2: Matched-random baseline generation for ES/VIX level discovery.

Deterministic baseline using 1,000 resamples matching on:
year, month (where possible), weekday, 30-min RTH bucket, direction,
VIX decile, roll-day status, and complete horizon availability.

Each random candidate calculates its own sigma_day from its session's
cash open and prior VIX close.

For each config × horizon × resample, one matched random observation is
selected for every eligible actual touch, then aggregated into one row.
"""
from __future__ import annotations

import hashlib
import math
from typing import Optional

import numpy as np
import pandas as pd

from research.es_vix_level_discovery.stage1_engine import (
    _rth_bars,
    FIXED_HORIZONS,
    FP_THRESHOLDS,
    TRADING_DAYS,
    NY_TZ,
)

BASE_SEED = "20260709_STAGE2_BASELINE"
N_RESAMPLES = 1000

SIGMA_VALS = [0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
PCT_OFFSETS = [0.0, 0.02, 0.04, 0.06, 0.08, 0.1]
FIXED_OFFSETS = [2.5, 5.0, 7.5, 10.0, 15.0]


def _session_seed(config_id: str, horizon: str, touch_id: str,
                  resample: int, master_seed: str) -> int:
    raw = f"{master_seed}_{config_id}_{horizon}_{touch_id}_{resample}"
    return int(hashlib.sha256(raw.encode()).hexdigest(), 16) % (2**32)


def _vix_decile_bounds(vix_df: pd.DataFrame) -> list[float]:
    vix_dev = vix_df[
        (vix_df["date"] >= "2018-01-01") & (vix_df["date"] <= "2019-12-31")
    ]
    vix_vals = vix_dev["vix_close"].dropna().values
    if len(vix_vals) == 0:
        return [-float("inf"), float("inf")]
    bounds = [float(np.quantile(vix_vals, i / 10)) for i in range(11)]
    bounds[0] = -float("inf")
    bounds[-1] = float("inf")
    return bounds


def _decile_index(vix_close: float, bounds: list[float]) -> int:
    for i in range(10):
        if bounds[i] <= vix_close < bounds[i + 1]:
            return i
    return 9


def _rth_time_bucket(ts: pd.Timestamp) -> str:
    hour = ts.hour
    minute = (ts.minute // 30) * 30
    return f"{hour:02d}:{minute:02d}"


def _horizon_available(
    bar_ts: pd.Timestamp, horizon_minutes: int, rth_by_session: dict
) -> bool:
    touch_session = bar_ts.strftime("%Y-%m-%d")
    session_bars = rth_by_session.get(touch_session)
    if session_bars is None or session_bars.empty:
        return False
    label_start = bar_ts + pd.Timedelta(minutes=1)
    requested_end = label_start + pd.Timedelta(minutes=horizon_minutes)
    session_close = pd.Timestamp(f"{touch_session} 16:00", tz=NY_TZ)
    if requested_end > session_close:
        return False
    post_bars = session_bars[session_bars["ny_time"] >= label_start]
    window_bars = post_bars[post_bars["ny_time"] < requested_end]
    return len(window_bars) >= horizon_minutes


def _build_session_meta(es_df: pd.DataFrame,
                        vix_df: pd.DataFrame,
                        vix_decile_bounds: list[float]) -> dict:
    """Build per-session metadata: cash_open, vix_close, sigma_day, decile."""
    rth = _rth_bars(es_df)
    vix = vix_df.copy()
    if "date" in vix.columns:
        vix["date"] = pd.to_datetime(vix["date"])
    meta = {}
    for sd in sorted(rth["session_date"].unique()):
        sb = rth[rth["session_date"] == sd].sort_values("ny_time")
        if sb.empty:
            continue
        cash_open = float(sb["open"].iloc[0])
        sess_dt = pd.Timestamp(sd)
        prior = vix[vix["date"] < sess_dt]
        if prior.empty:
            continue
        vix_close = float(prior["vix_close"].iloc[-1])
        sigma_day = cash_open * (vix_close / 100.0) / math.sqrt(TRADING_DAYS)
        decile = _decile_index(vix_close, vix_decile_bounds)
        meta[sd] = {
            "cash_open": cash_open,
            "vix_close": vix_close,
            "sigma_day": sigma_day,
            "vix_decile": decile,
        }
    return meta


def _build_eligible_pool(
    es_df: pd.DataFrame, vix_df: pd.DataFrame,
    vix_decile_bounds: list[float], session_meta: dict
) -> pd.DataFrame:
    """Build pool of eligible random timestamps with session metadata."""
    rth = _rth_bars(es_df)
    rows = []
    for _, bar in rth.iterrows():
        sd = bar["session_date"]
        if sd not in session_meta:
            continue
        meta = session_meta[sd]
        ny_ts = bar["ny_time"]
        rows.append({
            "ny_time": ny_ts,
            "session_date": sd,
            "open": float(bar["open"]),
            "high": float(bar["high"]),
            "low": float(bar["low"]),
            "close": float(bar["close"]),
            "contract": str(bar["contract"]),
            "roll_day": int(bar["roll_day"]),
            "cash_open": meta["cash_open"],
            "session_vix_close": meta["vix_close"],
            "session_sigma_day": meta["sigma_day"],
            "session_vix_decile": meta["vix_decile"],
        })
    pool = pd.DataFrame(rows)
    if pool.empty:
        return pool
    pool["year"] = pool["session_date"].str[:4]
    pool["month"] = pool["session_date"].str[5:7]
    pool["weekday"] = pool["ny_time"].dt.weekday
    pool["tod_bucket"] = pool["ny_time"].apply(_rth_time_bucket)
    return pool


def _compute_random_excursion(
    rand_entry: float, touch_direction: str, window_bars: pd.DataFrame,
    sigma_day: float
) -> dict:
    """Compute excursion metrics for a random entry."""
    fut_high = float(window_bars["high"].max())
    fut_low = float(window_bars["low"].min())
    if touch_direction == "SHORT":
        mfe = max(0.0, rand_entry - fut_low)
        mae = max(0.0, fut_high - rand_entry)
        close_ret = (rand_entry - float(window_bars["close"].iloc[-1])) / sigma_day if sigma_day != 0 else None
    else:
        mfe = max(0.0, fut_high - rand_entry)
        mae = max(0.0, rand_entry - fut_low)
        close_ret = (float(window_bars["close"].iloc[-1]) - rand_entry) / sigma_day if sigma_day != 0 else None

    fp_statuses = {}
    for thresh in FP_THRESHOLDS:
        if sigma_day == 0:
            fp_statuses[thresh] = "NOT_REACHED"
            continue
        thresh_pts = thresh * sigma_day
        if touch_direction == "SHORT":
            fav_price = rand_entry - thresh_pts
            adv_price = rand_entry + thresh_pts
        else:
            fav_price = rand_entry + thresh_pts
            adv_price = rand_entry - thresh_pts

        fav_idx = adv_idx = None
        for i_, bar in window_bars.iterrows():
            if touch_direction == "SHORT":
                if fav_idx is None and float(bar["low"]) <= fav_price:
                    fav_idx = i_
                if adv_idx is None and float(bar["high"]) >= adv_price:
                    adv_idx = i_
            else:
                if fav_idx is None and float(bar["high"]) >= fav_price:
                    fav_idx = i_
                if adv_idx is None and float(bar["low"]) <= adv_price:
                    adv_idx = i_

        if fav_idx is not None and adv_idx is not None:
            if fav_idx == adv_idx:
                fp_statuses[thresh] = "AMBIGUOUS"
            elif window_bars.index.get_loc(fav_idx) < window_bars.index.get_loc(adv_idx):
                fp_statuses[thresh] = "FAVORABLE_FIRST"
            else:
                fp_statuses[thresh] = "ADVERSE_FIRST"
        elif fav_idx is not None:
            fp_statuses[thresh] = "FAVORABLE_FIRST"
        elif adv_idx is not None:
            fp_statuses[thresh] = "ADVERSE_FIRST"
        else:
            fp_statuses[thresh] = "NOT_REACHED"

    return {
        "mfe": round(mfe, 6),
        "mae": round(mae, 6),
        "directional_return": round(close_ret, 6) if close_ret is not None else None,
        "mfe_sigma_ratio": round(mfe / sigma_day, 6) if sigma_day != 0 else None,
        "mae_sigma_ratio": round(mae / sigma_day, 6) if sigma_day != 0 else None,
        "fp_025_sigma": fp_statuses[0.25],
        "fp_050_sigma": fp_statuses[0.50],
        "fp_075_sigma": fp_statuses[0.75],
        "fp_100_sigma": fp_statuses[1.00],
    }


def build_baseline(
    touches_df: pd.DataFrame,
    levels_df: pd.DataFrame,
    es_df: pd.DataFrame,
    vix_df: pd.DataFrame,
    horizons: list[str],
    n_resamples: int = N_RESAMPLES,
    base_seed: str = BASE_SEED,
) -> dict:
    """Generate matched-random baseline for all configs and horizons.

    Parameters
    ----------
    touches_df : pd.DataFrame
        Stage 1 touches (must include overlap_cluster_id).
    levels_df : pd.DataFrame
        Stage 1 levels (needed for cash_open, vix_close, roll_day).
    es_df : pd.DataFrame
        Raw ES 1m dataframe (already filtered to 2018-2019).
    vix_df : pd.DataFrame
        VIX daily dataframe with date and vix_close.
    horizons : list[str]
        Horizon labels to compute baseline for (e.g. ["60m", "120m"]).

    Returns
    -------
    dict with:
        "aggregated": pd.DataFrame — one row per config/horizon/resample
        "summary": pd.DataFrame — BASELINE_RESULTS.csv content
        "vix_decile_bounds": list[float]
    """
    vix_decile_bounds = _vix_decile_bounds(vix_df)
    session_meta = _build_session_meta(es_df, vix_df, vix_decile_bounds)
    pool = _build_eligible_pool(es_df, vix_df, vix_decile_bounds, session_meta)
    rth = _rth_bars(es_df)
    rth_by_session = {
        sd: grp.sort_values("ny_time")
        for sd, grp in rth.groupby("session_date")
    }

    if pool.empty:
        return {
            "aggregated": pd.DataFrame(),
            "summary": pd.DataFrame(),
            "vix_decile_bounds": vix_decile_bounds,
        }

    # Merge touches with levels to get cash_open, vix_close, roll_day
    lvl_cols = ["level_id", "config_id", "cash_open", "vix_close",
                "vix_source_date", "sigma_day", "roll_day"]
    tch = touches_df.copy()
    lvls = levels_df[lvl_cols].drop_duplicates(subset=["level_id"])
    tch = tch.merge(lvls, on="level_id", how="left", suffixes=("", "_level"))

    horizon_map = {}
    for h in horizons:
        for fh in FIXED_HORIZONS:
            if h == f"{fh}m":
                horizon_map[h] = fh
                break

    detail_rows = []

    for cfg_id in sorted(tch["config_id"].unique()):
        cfg_touches = tch[tch["config_id"] == cfg_id]
        if cfg_touches.empty:
            continue

        for _, tr in cfg_touches.iterrows():
            touch_ts = pd.Timestamp(tr["touch_bar_timestamp"])
            sd = tr["session_touched"]
            touch_year = sd[:4]
            touch_month = sd[5:7]
            touch_weekday = touch_ts.weekday()
            touch_bucket = _rth_time_bucket(touch_ts)
            touch_direction = tr["touch_direction"]
            actual_vix_close = float(tr.get("vix_close", 15.0) or 15.0)
            actual_decile = _decile_index(actual_vix_close, vix_decile_bounds)
            actual_roll_day = int(tr.get("roll_day", 0))
            touch_id = tr["touch_id"]

            # Build matching pool
            matched = pool[
                (pool["year"] == touch_year)
                & (pool["month"] == touch_month)
                & (pool["weekday"] == touch_weekday)
                & (pool["tod_bucket"] == touch_bucket)
                & (pool["session_vix_decile"] == actual_decile)
                & (pool["roll_day"] == actual_roll_day)
            ].copy()

            fallback_used = False
            if matched.empty:
                # Fallback: drop month requirement
                matched = pool[
                    (pool["year"] == touch_year)
                    & (pool["weekday"] == touch_weekday)
                    & (pool["tod_bucket"] == touch_bucket)
                    & (pool["session_vix_decile"] == actual_decile)
                    & (pool["roll_day"] == actual_roll_day)
                ].copy()
                fallback_used = True

            if matched.empty:
                continue

            # Exclude actual touch bar and its entire label window
            exclude_mask = matched["ny_time"] == touch_ts
            for horizon_label, horizon_min in horizon_map.items():
                if horizon_min is None:
                    continue
                label_start = touch_ts + pd.Timedelta(minutes=1)
                label_end = label_start + pd.Timedelta(minutes=horizon_min)
                exclude_mask |= (
                    (matched["ny_time"] >= label_start)
                    & (matched["ny_time"] < label_end)
                )
            matched = matched[~exclude_mask]

            if matched.empty:
                continue

            for resample_i in range(n_resamples):
                for horizon_label, horizon_min in horizon_map.items():
                    seed = _session_seed(cfg_id, horizon_label, touch_id,
                                         resample_i, base_seed)
                    rng = np.random.default_rng(seed)

                    # Filter to bars with horizon availability
                    valid = matched[
                        matched["ny_time"].apply(
                            lambda ts: _horizon_available(
                                ts, horizon_min, rth_by_session
                            )
                        )
                    ]
                    if valid.empty:
                        continue

                    selected = valid.sample(n=1, random_state=rng).iloc[0]
                    rand_ts = selected["ny_time"]
                    rand_entry = float(selected["open"])
                    rand_session = selected["session_date"]
                    rand_sigma = float(selected["session_sigma_day"])

                    # Compute label window for random entry
                    label_start = rand_ts + pd.Timedelta(minutes=1)
                    requested_end = label_start + pd.Timedelta(minutes=horizon_min)
                    session_bars = rth_by_session.get(rand_session)
                    if session_bars is None:
                        continue
                    post_bars = session_bars[session_bars["ny_time"] >= label_start]
                    window_bars = post_bars[post_bars["ny_time"] < requested_end]
                    if window_bars.empty or len(window_bars) < horizon_min:
                        continue

                    exc = _compute_random_excursion(
                        rand_entry, touch_direction, window_bars, rand_sigma
                    )

                    detail_rows.append({
                        "config_id": cfg_id,
                        "horizon": horizon_label,
                        "resample": resample_i,
                        "touch_id": touch_id,
                        "random_timestamp": str(rand_ts),
                        "random_entry": rand_entry,
                        "mfe": exc["mfe"],
                        "mae": exc["mae"],
                        "mfe_sigma_ratio": exc["mfe_sigma_ratio"],
                        "mae_sigma_ratio": exc["mae_sigma_ratio"],
                        "directional_return": exc["directional_return"],
                        "fp_025_sigma": exc["fp_025_sigma"],
                        "fp_050_sigma": exc["fp_050_sigma"],
                        "fp_075_sigma": exc["fp_075_sigma"],
                        "fp_100_sigma": exc["fp_100_sigma"],
                        "fallback_used": fallback_used,
                        "rand_sigma_day": rand_sigma,
                    })

    detail = pd.DataFrame(detail_rows)

    # Aggregate: one row per config × horizon × resample
    agg_rows = []
    if not detail.empty:
        for (cfg_id, horizon_label, resample_i), grp in detail.groupby(
            ["config_id", "horizon", "resample"], sort=False
        ):
            mfes = grp["mfe"].dropna()
            maes = grp["mae"].dropna()
            rets = grp["directional_return"].dropna()
            agg_rows.append({
                "config_id": cfg_id,
                "horizon": horizon_label,
                "resample": resample_i,
                "selected_count": len(grp),
                "median_mfe_points": float(np.median(mfes)) if len(mfes) > 0 else None,
                "median_mae_points": float(np.median(maes)) if len(maes) > 0 else None,
                "p90_mae_points": float(np.quantile(maes, 0.90)) if len(maes) > 0 else None,
                "p95_mae_points": float(np.quantile(maes, 0.95)) if len(maes) > 0 else None,
                "mean_directional_return_over_sigma": float(np.mean(rets)) if len(rets) > 0 else None,
                "median_directional_return_over_sigma": float(np.median(rets)) if len(rets) > 0 else None,
                "positive_directional_return_rate": float((rets > 0).sum() / len(rets)) if len(rets) > 0 else None,
                "p_favorable_first_0.25": float((grp["fp_025_sigma"] == "FAVORABLE_FIRST").sum() / len(grp)) if len(grp) > 0 else None,
                "p_adverse_first_0.25": float((grp["fp_025_sigma"] == "ADVERSE_FIRST").sum() / len(grp)) if len(grp) > 0 else None,
                "p_ambiguous_0.25": float((grp["fp_025_sigma"] == "AMBIGUOUS").sum() / len(grp)) if len(grp) > 0 else None,
                "p_neither_reached_0.25": float((grp["fp_025_sigma"] == "NOT_REACHED").sum() / len(grp)) if len(grp) > 0 else None,
                "p_favorable_first_0.50": float((grp["fp_050_sigma"] == "FAVORABLE_FIRST").sum() / len(grp)) if len(grp) > 0 else None,
                "p_adverse_first_0.50": float((grp["fp_050_sigma"] == "ADVERSE_FIRST").sum() / len(grp)) if len(grp) > 0 else None,
                "p_ambiguous_0.50": float((grp["fp_050_sigma"] == "AMBIGUOUS").sum() / len(grp)) if len(grp) > 0 else None,
                "p_neither_reached_0.50": float((grp["fp_050_sigma"] == "NOT_REACHED").sum() / len(grp)) if len(grp) > 0 else None,
                "p_favorable_first_0.75": float((grp["fp_075_sigma"] == "FAVORABLE_FIRST").sum() / len(grp)) if len(grp) > 0 else None,
                "p_adverse_first_0.75": float((grp["fp_075_sigma"] == "ADVERSE_FIRST").sum() / len(grp)) if len(grp) > 0 else None,
                "p_ambiguous_0.75": float((grp["fp_075_sigma"] == "AMBIGUOUS").sum() / len(grp)) if len(grp) > 0 else None,
                "p_neither_reached_0.75": float((grp["fp_075_sigma"] == "NOT_REACHED").sum() / len(grp)) if len(grp) > 0 else None,
                "p_favorable_first_1.00": float((grp["fp_100_sigma"] == "FAVORABLE_FIRST").sum() / len(grp)) if len(grp) > 0 else None,
                "p_adverse_first_1.00": float((grp["fp_100_sigma"] == "ADVERSE_FIRST").sum() / len(grp)) if len(grp) > 0 else None,
                "p_ambiguous_1.00": float((grp["fp_100_sigma"] == "AMBIGUOUS").sum() / len(grp)) if len(grp) > 0 else None,
                "p_neither_reached_1.00": float((grp["fp_100_sigma"] == "NOT_REACHED").sum() / len(grp)) if len(grp) > 0 else None,
                "rand_sigma_day_used": float(grp["rand_sigma_day"].iloc[0]),
            })

    aggregated = pd.DataFrame(agg_rows)

    # Summary: across all resamples for each config × horizon
    summary_rows = []
    if not aggregated.empty:
        for (cfg_id, horizon_label), grp in aggregated.groupby(
            ["config_id", "horizon"], sort=False
        ):
            metrics = {
                "selected_count": grp["selected_count"].sum(),
                "median_mfe_points": grp["median_mfe_points"].dropna(),
                "median_mae_points": grp["median_mae_points"].dropna(),
                "p90_mae_points": grp["p90_mae_points"].dropna(),
                "p95_mae_points": grp["p95_mae_points"].dropna(),
                "mean_directional_return_over_sigma": grp["mean_directional_return_over_sigma"].dropna(),
                "median_directional_return_over_sigma": grp["median_directional_return_over_sigma"].dropna(),
                "positive_directional_return_rate": grp["positive_directional_return_rate"].dropna(),
            }
            row = {"config_id": cfg_id, "horizon": horizon_label}
            for metric_name, vals in metrics.items():
                if len(vals) > 0:
                    row[metric_name] = float(np.median(vals))
                else:
                    row[metric_name] = None
            # First-passage across all resamples
            for thresh_label in ["0.25", "0.50", "0.75", "1.00"]:
                for fp_type in ["p_favorable_first", "p_adverse_first",
                                "p_ambiguous", "p_neither_reached"]:
                    col = f"{fp_type}_{thresh_label}"
                    vals = grp[col].dropna()
                    if len(vals) > 0:
                        row[col] = float(np.median(vals))
                    else:
                        row[col] = None
            summary_rows.append(row)

    summary = pd.DataFrame(summary_rows)

    return {
        "aggregated": aggregated,
        "summary": summary,
        "vix_decile_bounds": vix_decile_bounds,
    }


def compute_baseline_lift(
    actual_metrics: pd.DataFrame,
    baseline_aggregated: pd.DataFrame,
    horizons: list[str],
) -> pd.DataFrame:
    """Compute baseline lift per config per horizon.

    Reports:
    - baseline median, p05, p95
    - actual-minus-baseline
    - percentage lift (only with valid denominator)
    - actual empirical percentile
    - one-sided empirical p-value

    Respects metric direction: higher MFE/return/favorable-first is better;
    lower MAE/adverse-first is better.
    """
    rows = []

    METRIC_CONFIG = {
        "median_mfe_points": {"higher_is_better": True},
        "median_mae_points": {"higher_is_better": False},
        "mean_directional_return_over_sigma": {"higher_is_better": True},
        "positive_directional_return_rate": {"higher_is_better": True},
    }

    for _, actual_row in actual_metrics.iterrows():
        cfg_id = actual_row["config_id"]
        horizon = actual_row["horizon"]
        if horizon not in horizons:
            continue

        bs = baseline_aggregated[
            (baseline_aggregated["config_id"] == cfg_id)
            & (baseline_aggregated["horizon"] == horizon)
        ]
        if bs.empty:
            continue

        for metric, config in METRIC_CONFIG.items():
            actual_val = actual_row.get(metric)
            if actual_val is None:
                continue

            random_vals = bs[metric].dropna().values
            if len(random_vals) < 2:
                continue

            baseline_median = float(np.median(random_vals))
            baseline_p05 = float(np.quantile(random_vals, 0.05))
            baseline_p95 = float(np.quantile(random_vals, 0.95))
            actual_minus_baseline = actual_val - baseline_median

            if baseline_median != 0:
                pct_lift = actual_minus_baseline / abs(baseline_median)
            else:
                pct_lift = None

            # Actual empirical percentile
            below = float((random_vals < actual_val).sum())
            actual_percentile = below / len(random_vals)

            # One-sided empirical p-value
            if config["higher_is_better"]:
                p_value = 1.0 - float((random_vals < actual_val).sum()) / len(random_vals)
            else:
                p_value = float((random_vals < actual_val).sum()) / len(random_vals)

            rows.append({
                "config_id": cfg_id,
                "horizon": horizon,
                "metric": metric,
                "actual_value": actual_val,
                "baseline_median": baseline_median,
                "baseline_p05": baseline_p05,
                "baseline_p95": baseline_p95,
                "actual_minus_baseline": actual_minus_baseline,
                "percentage_lift": pct_lift,
                "actual_percentile": actual_percentile,
                "one_sided_p_value": p_value,
                "n_random_observations": len(random_vals),
            })
    return pd.DataFrame(rows)
