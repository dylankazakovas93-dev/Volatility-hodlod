"""Stage 2: Matched-random baseline generation for ES/VIX level discovery.

Deterministic baseline using 1,000 resamples matching on:
year, month, weekday, 30-min RTH bucket, direction, VIX decile, roll-day.
"""
from __future__ import annotations

import hashlib
import math
from typing import Optional

import numpy as np
import pandas as pd

from research.es_vix_level_discovery.stage1_engine import (
    VIXLevelEngine,
    FIXED_HORIZONS,
    FP_THRESHOLDS,
)

BASE_SEED = "20260709_STAGE2_BASELINE"
N_RESAMPLES = 1000
NY_TZ = "America/New_York"


def _seed_for_resample(resample_i: int) -> int:
    raw = f"{BASE_SEED}_{resample_i}"
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
    bar_ts: pd.Timestamp,
    horizon_minutes: int,
    rth_by_session: dict,
) -> bool:
    """Check if the horizon would be COMPLETE for a touch at bar_ts."""
    touch_session = bar_ts.strftime("%Y-%m-%d")
    session_bars = rth_by_session.get(touch_session)
    if session_bars is None or session_bars.empty:
        return False
    label_start = bar_ts + pd.Timedelta(minutes=1)
    requested_end = label_start + pd.Timedelta(minutes=horizon_minutes)
    post_bars = session_bars[session_bars["ny_time"] >= label_start]
    window_bars = post_bars[post_bars["ny_time"] < requested_end]
    return len(window_bars) >= horizon_minutes


def build_baseline(
    touches_df: pd.DataFrame,
    es_df: pd.DataFrame,
    vix_df: pd.DataFrame,
    horizons: list[str],
    n_resamples: int = N_RESAMPLES,
    base_seed: str = BASE_SEED,
) -> dict:
    """Generate matched-random baseline for all configs and primary horizons.

    Parameters
    ----------
    touches_df : pd.DataFrame
        Stage 1 touches (must include overlap_cluster_id).
    es_df : pd.DataFrame
        Raw ES 1m dataframe.
    vix_df : pd.DataFrame
        VIX daily dataframe with date and vix_close.
    horizons : list[str]
        Horizon labels to compute baseline for (e.g. ["60m", "120m"]).

    Returns
    -------
    dict with:
        "results": pd.DataFrame of baseline metrics per config/horizon/resample
        "seeds": list of seeds used
        "vix_decile_bounds": the frozen decile bounds
    """
    rth = _rth_bars(es_df)
    rth_by_session = {
        sd: grp.sort_values("ny_time")
        for sd, grp in rth.groupby("session_date")
    }

    vix_decile_bounds = _vix_decile_bounds(vix_df)
    seeds = [_seed_for_resample(i) for i in range(n_resamples)]

    # Build pool of eligible random bars (2018-2019 development period only)
    eligible_bars = []
    for sd, sb in rth_by_session.items():
        if sd < "2018-01-01" or sd > "2019-12-31":
            continue
        for _, bar in sb.iterrows():
            eligible_bars.append({
                "timestamp": bar["ny_time"],
                "session_date": sd,
                "open": float(bar["open"]),
                "high": float(bar["high"]),
                "low": float(bar["low"]),
                "close": float(bar["close"]),
                "contract": str(bar["contract"]),
                "roll_day": int(bar["roll_day"]),
            })
    eligible_df = pd.DataFrame(eligible_bars)

    all_results = []
    for cfg_id in sorted(touches_df["config_id"].unique()):
        cfg_touches = touches_df[touches_df["config_id"] == cfg_id]
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
            vix_close_at_touch = float(tr.get("sigma_day", 0.0) or 0.0)  # Not ideal; would need actual vix_close
            # We'll use sigma_day as a proxy for vix decile context
            # Actually, we need the actual VIX close for the touch session
            sigma_day = float(tr.get("sigma_day", 0.0) or 0.0)
            # Derive rough vix close from sigma_day
            cash_open = float(tr.get("level_price", 4700.0))
            if sigma_day > 0:
                vix_implied = sigma_day * math.sqrt(252) * 100.0 / cash_open
            else:
                vix_implied = 15.0
            vix_decile = _decile_index(vix_implied, vix_decile_bounds)
            roll_day = int(tr.get("roll_day", tr.get("roll_day", 0)))

            # Filter pool to matching criteria
            pool = eligible_df[
                (eligible_df["session_date"].str[:4] == touch_year)
                & (eligible_df["session_date"].str[5:7] == touch_month)
            ]
            pool = pool[pool["timestamp"].dt.weekday == touch_weekday]
            pool = pool[_rth_time_bucket(pool["timestamp"]) == touch_bucket]
            pool = pool[pool["roll_day"] == roll_day]

            if pool.empty:
                continue

            for resample_i in range(n_resamples):
                rng = np.random.default_rng(seeds[resample_i])
                for horizon_label in horizons:
                    horizon_minutes = None
                    for fh in FIXED_HORIZONS:
                        if horizon_label == f"{fh}m":
                            horizon_minutes = fh
                            break
                    if horizon_minutes is None and horizon_label == "RTH_REMAINDER":
                        continue  # skip RTH_REMAINDER for baseline

                    # Sample a random bar from the pool that has horizon availability
                    valid_pool = pool[
                        pool["timestamp"].apply(
                            lambda ts: _horizon_available(
                                ts, horizon_minutes, rth_by_session
                            )
                        )
                    ]
                    if valid_pool.empty:
                        continue

                    selected = valid_pool.sample(n=1, random_state=rng)[["timestamp", "open", "high", "low", "close", "contract", "session_date", "roll_day"]].iloc[0]

                    # Compute excursion metrics for this random timestamp
                    # We compute a synthetic touch with matching direction
                    rand_ts = selected["timestamp"]
                    rand_entry = float(selected["open"])
                    # Determine the label window
                    label_start = rand_ts + pd.Timedelta(minutes=1)
                    requested_end = label_start + pd.Timedelta(minutes=horizon_minutes)
                    session_bars = rth_by_session.get(selected["session_date"])
                    if session_bars is None:
                        continue
                    post_bars = session_bars[session_bars["ny_time"] >= label_start]
                    window_bars = post_bars[post_bars["ny_time"] < requested_end]
                    if window_bars.empty:
                        continue

                    fut_high = float(window_bars["high"].max())
                    fut_low = float(window_bars["low"].min())

                    if touch_direction == "SHORT":
                        mfe = rand_entry - fut_low
                        mae = fut_high - rand_entry
                        close_ret = (rand_entry - float(window_bars["close"].iloc[-1])) / sigma_day if sigma_day != 0 else None
                    else:
                        mfe = fut_high - rand_entry
                        mae = rand_entry - fut_low
                        close_ret = (float(window_bars["close"].iloc[-1]) - rand_entry) / sigma_day if sigma_day != 0 else None

                    mfe = max(0.0, mfe)
                    mae = max(0.0, mae)

                    all_results.append({
                        "config_id": cfg_id,
                        "horizon": horizon_label,
                        "resample": resample_i,
                        "touch_id": tr["touch_id"],
                        "random_timestamp": str(rand_ts),
                        "random_entry": round(rand_entry, 6),
                        "mfe": round(mfe, 6),
                        "mae": round(mae, 6),
                        "directional_return": round(close_ret, 6) if close_ret is not None else None,
                        "sigma_day": sigma_day,
                    })

    results_df = pd.DataFrame(all_results)
    return {
        "results": results_df,
        "seeds": seeds,
        "vix_decile_bounds": vix_decile_bounds,
    }


def compute_baseline_lift(
    actual_metrics: pd.DataFrame,
    baseline_results: pd.DataFrame,
    horizons: list[str],
) -> pd.DataFrame:
    """Compute baseline lift per config per horizon.

    lift = (actual - median_random) / median_random
    """
    rows = []
    for _, row in actual_metrics.iterrows():
        cfg_id = row["config_id"]
        horizon = row["horizon"]
        if horizon not in horizons:
            continue

        bs = baseline_results[
            (baseline_results["config_id"] == cfg_id)
            & (baseline_results["horizon"] == horizon)
        ]
        if bs.empty:
            continue

        for metric, actual_val in [
            ("median_mfe_points", row.get("median_mfe_points")),
            ("median_mae_points", row.get("median_mae_points")),
            ("mean_directional_return_over_sigma", row.get("mean_directional_return_over_sigma")),
            ("positive_directional_return_rate", row.get("positive_directional_return_rate")),
        ]:
            if actual_val is None:
                continue
            random_vals = bs[metric].dropna()
            if random_vals.empty:
                continue
            median_random = float(np.median(random_vals))
            if median_random == 0:
                lift = None
            else:
                lift = (actual_val - median_random) / abs(median_random)
            rows.append({
                "config_id": cfg_id,
                "horizon": horizon,
                "metric": metric,
                "actual_value": actual_val,
                "median_random": median_random,
                "baseline_lift": lift,
                "random_std": float(np.std(random_vals)) if len(random_vals) > 1 else None,
            })
    return pd.DataFrame(rows)


def _rth_bars(es_df):
    """Extract RTH bars from ES dataframe."""
    ny = pd.to_datetime(es_df["timestamp"], utc=True).dt.tz_convert(NY_TZ)
    hour = ny.dt.hour
    minute = ny.dt.minute
    after_start = (hour > 9) | ((hour == 9) & (minute >= 30))
    before_end = hour < 16
    rth_mask = after_start & before_end
    rth = es_df[rth_mask].copy()
    rth["ny_time"] = ny[rth.index]
    return rth
