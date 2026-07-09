"""Stage 1: Deterministic ES/VIX level-generation, touch-detection, excursion
engine for a single preregistered grid configuration.

Every public method is deterministic (no RNG, stable ordering).
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Optional

import pandas as pd

TRADING_DAYS = 252.0
RTH_START = "09:30"
RTH_END = "16:00"
NY_TZ = "America/New_York"
LEVEL_NAMESPACE = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")

FP_THRESHOLDS = [0.25, 0.50, 0.75, 1.00]
FIXED_HORIZONS = [15, 30, 60, 120]


@dataclass(frozen=True)
class LevelConfig:
    config_id: str
    sigma_multiplier: float
    ib_minutes: int
    offset_family: str
    offset_parameter: str
    offset_value: float
    line_life_sessions: int = 20


def _ny_time(ts_series: pd.Series) -> pd.Series:
    return pd.to_datetime(ts_series, utc=True).dt.tz_convert(NY_TZ)


def _is_rth(ny: pd.Series) -> pd.Series:
    hour = ny.dt.hour
    minute = ny.dt.minute
    after_start = (hour > 9) | ((hour == 9) & (minute >= 30))
    before_end = (hour < 16)
    return after_start & before_end


def _rth_bars(es_df: pd.DataFrame) -> pd.DataFrame:
    ny = _ny_time(es_df["timestamp"])
    rth = es_df[_is_rth(ny)].copy()
    rth.loc[:, "ny_time"] = ny[rth.index]
    return rth


def _prior_vix_close(vix_df: pd.DataFrame, session_date: str) -> Optional[float]:
    sd = pd.Timestamp(session_date)
    prior = vix_df[vix_df["date"] < sd]
    if prior.empty:
        return None
    return float(prior["vix_close"].iloc[-1])


def _vix_source_date(vix_df: pd.DataFrame, session_date: str) -> Optional[str]:
    sd = pd.Timestamp(session_date)
    prior = vix_df[vix_df["date"] < sd]
    if prior.empty:
        return None
    return str(prior["date"].iloc[-1])


def _vix_available_at(session_date: str) -> str:
    return f"{session_date} 09:30:00"


def _generate_level_id(config_id: str, session_date: str, direction: str) -> str:
    raw = f"{config_id}_{session_date}_{direction}"
    return str(uuid.uuid5(LEVEL_NAMESPACE, raw))


def _generate_touch_id(level_id: str, bar_ts: str) -> str:
    raw = f"{level_id}_{bar_ts}"
    return str(uuid.uuid5(LEVEL_NAMESPACE, raw))


def _session_available_reason(
    session_bars: pd.DataFrame, ib_minutes: int, sd: str
) -> Optional[str]:
    """Return None if session is usable, otherwise a reason string."""
    ny_session = session_bars["ny_time"]
    ib_start = pd.Timestamp(f"{sd} 09:30", tz=NY_TZ)
    ib_end = ib_start + pd.Timedelta(minutes=ib_minutes)
    ib_mask = (ny_session >= ib_start) & (ny_session <= ib_end)
    ib_bars = session_bars[ib_mask]
    if ib_bars.empty:
        return "no_ib_bars"
    first_bar_time = session_bars["ny_time"].iloc[0]
    if first_bar_time != ib_start:
        return f"session_does_not_start_at_rth_open_{first_bar_time}"
    last_ib_index = ib_bars.index[-1]
    last_ib_time = ib_bars["ny_time"].iloc[-1]
    if last_ib_time != ib_end:
        return f"ib_cutoff_bar_missing_{ib_end}"
    created_candidates = session_bars.loc[session_bars["ny_time"] >= ib_end]
    if created_candidates.empty:
        return "no_creation_bar"
    if len(created_candidates) < 2:
        return "no_first_eligible_bar"
    return None


class VIXLevelEngine:
    """Deterministic level generation and touch detection for one config."""

    LEVEL_COLUMNS = [
        "level_id", "config_id", "session_date", "direction",
        "level_price", "cash_open", "vix_close", "vix_source_date",
        "vix_available_at", "sigma_day", "sigma_multiplier",
        "imp_up", "imp_dn",
        "ib_high", "ib_low", "ib_range", "ib_ext_up", "ib_ext_dn",
        "sigma_offset", "offset_family", "offset_parameter",
        "offset_value", "ib_minutes",
        "created_at", "first_eligible_at",
        "expiry_session", "line_life_sessions",
        "source_contract", "roll_day",
    ]

    def __init__(self, config: LevelConfig):
        self.config = config

    def generate_levels(
        self, es_df: pd.DataFrame, vix_df: pd.DataFrame
    ) -> pd.DataFrame:
        rows = []
        rth = _rth_bars(es_df)
        session_dates = sorted(rth["session_date"].unique())

        for sd in session_dates:
            session_bars = rth[rth["session_date"] == sd].sort_values("ny_time")
            if session_bars.empty:
                continue

            reason = _session_available_reason(
                session_bars, self.config.ib_minutes, sd
            )
            if reason is not None:
                continue

            cash_open = float(session_bars["open"].iloc[0])
            prior_vix = _prior_vix_close(vix_df, sd)
            if prior_vix is None:
                continue
            vix_src_date = _vix_source_date(vix_df, sd)
            vix_avail = _vix_available_at(sd)

            sigma_day = cash_open * (prior_vix / 100.0) / math.sqrt(TRADING_DAYS)

            ny_session = session_bars["ny_time"]
            ib_start = pd.Timestamp(f"{sd} 09:30", tz=NY_TZ)
            ib_end = ib_start + pd.Timedelta(minutes=self.config.ib_minutes)

            ib_mask = (ny_session >= ib_start) & (ny_session <= ib_end)
            ib_bars = session_bars[ib_mask]

            ib_high = float(ib_bars["high"].max())
            ib_low = float(ib_bars["low"].min())
            ib_range = ib_high - ib_low
            ib_ext_up = ib_high + ib_range
            ib_ext_dn = ib_low - ib_range

            imp_up = cash_open + self.config.sigma_multiplier * sigma_day
            imp_dn = cash_open - self.config.sigma_multiplier * sigma_day

            if self.config.offset_family == "fixed":
                sigma_offset = float(self.config.offset_value)
            else:
                sigma_offset = sigma_day * self.config.offset_value

            upper_level = (ib_ext_up + imp_up) / 2.0 - sigma_offset
            lower_level = (ib_ext_dn + imp_dn) / 2.0 + sigma_offset

            created_bar = session_bars.loc[
                session_bars["ny_time"] >= ib_end
            ].iloc[0]
            created_at = str(created_bar["ny_time"])

            first_eligible_bars = session_bars.loc[
                session_bars["ny_time"] > created_bar["ny_time"]
            ]
            first_eligible_at = str(first_eligible_bars.iloc[0]["ny_time"])

            session_idx = session_dates.index(sd)
            last_eligible_idx = min(
                session_idx + self.config.line_life_sessions - 1,
                len(session_dates) - 1,
            )
            expiry_session = session_dates[last_eligible_idx]

            source_contract = str(session_bars["contract"].iloc[0])
            roll_day_val = int(session_bars["roll_day"].iloc[0])

            for direction, level_price in [("UPPER", upper_level), ("LOWER", lower_level)]:
                level_id = _generate_level_id(self.config.config_id, sd, direction)
                rows.append({
                    "level_id": level_id,
                    "config_id": self.config.config_id,
                    "session_date": sd,
                    "direction": direction,
                    "level_price": round(level_price, 6),
                    "cash_open": round(cash_open, 6),
                    "vix_close": round(prior_vix, 6),
                    "vix_source_date": vix_src_date,
                    "vix_available_at": vix_avail,
                    "sigma_day": round(sigma_day, 10),
                    "sigma_multiplier": self.config.sigma_multiplier,
                    "imp_up": round(imp_up, 6),
                    "imp_dn": round(imp_dn, 6),
                    "ib_high": round(ib_high, 6),
                    "ib_low": round(ib_low, 6),
                    "ib_range": round(ib_range, 6),
                    "ib_ext_up": round(ib_ext_up, 6),
                    "ib_ext_dn": round(ib_ext_dn, 6),
                    "sigma_offset": round(sigma_offset, 6),
                    "offset_family": self.config.offset_family,
                    "offset_parameter": self.config.offset_parameter,
                    "offset_value": self.config.offset_value,
                    "ib_minutes": self.config.ib_minutes,
                    "created_at": created_at,
                    "first_eligible_at": first_eligible_at,
                    "expiry_session": expiry_session,
                    "line_life_sessions": self.config.line_life_sessions,
                    "source_contract": source_contract,
                    "roll_day": roll_day_val,
                })

        if not rows:
            return pd.DataFrame(columns=self.LEVEL_COLUMNS)
        return pd.DataFrame(rows)

    TOUCH_COLUMNS = [
        "touch_id", "level_id", "config_id",
        "level_direction", "touch_direction",
        "level_price",
        "touch_bar_timestamp", "touch_bar_open", "touch_bar_high",
        "touch_bar_low",
        "reference_entry_price", "gap_through",
        "session_created", "session_touched",
        "level_age_sessions", "level_age_minutes",
        "sigma_day", "vix_source_date", "vix_available_at",
        "ib_range",
        "deterministic_order", "overlap_cluster_id",
    ]

    @staticmethod
    def detect_touches(
        levels_df: pd.DataFrame, es_df: pd.DataFrame
    ) -> pd.DataFrame:
        rows = []
        rth = _rth_bars(es_df)
        session_dates = sorted(rth["session_date"].unique())

        rth_by_session = {
            sd: grp.sort_values("ny_time")
            for sd, grp in rth.groupby("session_date")
        }

        level_records = levels_df.to_dict("records")

        level_records.sort(
            key=lambda lr: (lr["created_at"], 0 if lr["direction"] == "UPPER" else 1, lr["level_id"])
        )

        for det_order, lr in enumerate(level_records, start=1):
            session_idx = session_dates.index(lr["session_date"])
            line_life = int(lr.get("line_life_sessions", 20))
            max_session_idx = min(
                session_idx + line_life, len(session_dates)
            )
            created_ts = pd.Timestamp(lr["created_at"])
            level_price = lr["level_price"]
            is_upper = lr["direction"] == "UPPER"

            first_eligible_ts = pd.Timestamp(lr["first_eligible_at"])

            touched = None
            for si in range(session_idx, max_session_idx):
                sd = session_dates[si]
                sb = rth_by_session.get(sd)
                if sb is None or sb.empty:
                    continue
                for _, bar in sb.iterrows():
                    bar_ts = bar["ny_time"]
                    if bar_ts < first_eligible_ts:
                        continue
                    bar_open = float(bar["open"])
                    bar_high = float(bar["high"])
                    bar_low = float(bar["low"])

                    if is_upper:
                        if bar_high >= level_price:
                            gap = bar_open > level_price
                            ref_price = bar_open if gap else level_price
                        else:
                            continue
                    else:
                        if bar_low <= level_price:
                            gap = bar_open < level_price
                            ref_price = bar_open if gap else level_price
                        else:
                            continue

                    level_age_sessions = si - session_idx
                    level_age_minutes = int(
                        (bar_ts - created_ts).total_seconds() // 60
                    )

                    touched = {
                        "touch_id": _generate_touch_id(
                            lr["level_id"], str(bar_ts)
                        ),
                        "level_id": lr["level_id"],
                        "config_id": lr["config_id"],
                        "level_direction": lr["direction"],
                        "touch_direction": "SHORT" if is_upper else "LONG",
                        "level_price": level_price,
                        "touch_bar_timestamp": str(bar_ts),
                        "touch_bar_open": round(bar_open, 6),
                        "touch_bar_high": round(bar_high, 6),
                        "touch_bar_low": round(bar_low, 6),
                        "reference_entry_price": round(ref_price, 6),
                        "gap_through": gap,
                        "session_created": lr["session_date"],
                        "session_touched": sd,
                        "level_age_sessions": level_age_sessions,
                        "level_age_minutes": level_age_minutes,
                        "sigma_day": lr.get("sigma_day"),
                        "vix_source_date": lr.get("vix_source_date"),
                        "vix_available_at": lr.get("vix_available_at"),
                        "ib_range": lr.get("ib_range"),
                        "deterministic_order": det_order,
                    }
                    break
                if touched is not None:
                    break

            if touched is None:
                continue

            rows.append(touched)

        if not rows:
            return pd.DataFrame(columns=VIXLevelEngine.TOUCH_COLUMNS)
        result = pd.DataFrame(rows)
        result["overlap_cluster_id"] = 0
        return result

    EXCURSION_COLUMNS = [
        "touch_id", "config_id", "level_direction", "touch_direction",
        "horizon", "label_status",
        "label_start", "requested_end_exclusive", "actual_last_bar",
        "required_bar_count", "actual_bar_count",
        "mae", "mfe",
        "mae_sigma_ratio", "mfe_sigma_ratio",
        "mae_ib_range_ratio", "mfe_ib_range_ratio",
        "directional_horizon_close_return_sigma",
        "sigma_day",
        "fp_025_sigma", "fp_050_sigma", "fp_075_sigma", "fp_100_sigma",
        "fp_025_timestamp", "fp_050_timestamp", "fp_075_timestamp",
        "fp_100_timestamp",
    ]

    @staticmethod
    def compute_excursions(
        touches_df: pd.DataFrame, es_df: pd.DataFrame
    ) -> pd.DataFrame:
        if touches_df.empty:
            return pd.DataFrame(columns=VIXLevelEngine.EXCURSION_COLUMNS)
        rows_list = []
        rth = _rth_bars(es_df)
        rth_by_session = {
            sd: grp.sort_values("ny_time")
            for sd, grp in rth.groupby("session_date")
        }

        for _, tr in touches_df.iterrows():
            touch_ts = pd.Timestamp(tr["touch_bar_timestamp"])
            touch_session = tr["session_touched"]
            entry_price = tr["reference_entry_price"]
            is_short = tr["touch_direction"] == "SHORT"
            sigma_day_val = float(tr["sigma_day"]) if tr["sigma_day"] is not None else None
            ib_range_val = float(tr.get("ib_range", 0.0)) if tr.get("ib_range") is not None else None
            session_bars = rth_by_session.get(touch_session)
            if session_bars is None or session_bars.empty:
                continue

            session_close_ts = pd.Timestamp(
                f"{touch_session} 16:00", tz=NY_TZ
            )

            for horizon_name, horizon_mins in (
                [("RTH_REMAINDER", None)]
                + [(f"{h}m", h) for h in FIXED_HORIZONS]
            ):
                label_start = touch_ts + pd.Timedelta(minutes=1)

                if horizon_mins is not None:
                    requested_end = label_start + pd.Timedelta(minutes=horizon_mins)
                else:
                    requested_end = session_close_ts

                post_touch_bars = session_bars.loc[
                    session_bars["ny_time"] >= label_start
                ]

                if horizon_mins is not None:
                    window_bars = post_touch_bars.loc[
                        post_touch_bars["ny_time"] < requested_end
                    ]
                else:
                    window_bars = post_touch_bars.loc[
                        post_touch_bars["ny_time"] <= session_close_ts
                    ]
                    actual_last = window_bars["ny_time"].iloc[-1] if not window_bars.empty else None
                    if actual_last is not None and actual_last >= session_close_ts:
                        window_bars = window_bars.loc[
                            window_bars["ny_time"] < session_close_ts
                        ]

                if horizon_mins is not None:
                    required = horizon_mins
                else:
                    required = None

                actual_count = len(window_bars)

                if horizon_mins is not None:
                    if actual_count < required:
                        rows_list.append({
                            "touch_id": tr["touch_id"],
                            "config_id": tr["config_id"],
                            "level_direction": tr["level_direction"],
                            "touch_direction": tr["touch_direction"],
                            "horizon": horizon_name,
                            "label_status": "INCOMPLETE",
                            "label_start": str(label_start),
                            "requested_end_exclusive": str(requested_end),
                            "actual_last_bar": (
                                str(window_bars["ny_time"].iloc[-1])
                                if not window_bars.empty else None
                            ),
                            "required_bar_count": required,
                            "actual_bar_count": actual_count,
                            "mae": None,
                            "mfe": None,
                            "mae_sigma_ratio": None,
                            "mfe_sigma_ratio": None,
                            "mae_ib_range_ratio": None,
                            "mfe_ib_range_ratio": None,
                            "directional_horizon_close_return_sigma": None,
                            "sigma_day": sigma_day_val,
                            "fp_025_sigma": "INCOMPLETE",
                            "fp_050_sigma": "INCOMPLETE",
                            "fp_075_sigma": "INCOMPLETE",
                            "fp_100_sigma": "INCOMPLETE",
                            "fp_025_timestamp": None,
                            "fp_050_timestamp": None,
                            "fp_075_timestamp": None,
                            "fp_100_timestamp": None,
                        })
                        continue

                if window_bars.empty:
                    rows_list.append({
                        "touch_id": tr["touch_id"],
                        "config_id": tr["config_id"],
                        "level_direction": tr["level_direction"],
                        "touch_direction": tr["touch_direction"],
                        "horizon": horizon_name,
                        "label_status": "INCOMPLETE",
                        "label_start": str(label_start),
                        "requested_end_exclusive": str(requested_end),
                        "actual_last_bar": None,
                        "required_bar_count": required,
                        "actual_bar_count": 0,
                        "mae": None,
                        "mfe": None,
                        "mae_sigma_ratio": None,
                        "mfe_sigma_ratio": None,
                        "mae_ib_range_ratio": None,
                        "mfe_ib_range_ratio": None,
                        "directional_horizon_close_return_sigma": None,
                        "sigma_day": sigma_day_val,
                        "fp_025_sigma": "INCOMPLETE",
                        "fp_050_sigma": "INCOMPLETE",
                        "fp_075_sigma": "INCOMPLETE",
                        "fp_100_sigma": "INCOMPLETE",
                        "fp_025_timestamp": None,
                        "fp_050_timestamp": None,
                        "fp_075_timestamp": None,
                        "fp_100_timestamp": None,
                    })
                    continue

                fut_high = float(window_bars["high"].max())
                fut_low = float(window_bars["low"].min())

                if is_short:
                    mfe = entry_price - fut_low
                    mae = fut_high - entry_price
                else:
                    mfe = fut_high - entry_price
                    mae = entry_price - fut_low

                mfe = round(max(0.0, mfe), 6)
                mae = round(max(0.0, mae), 6)

                mae_sigma = round(mae / sigma_day_val, 6) if (sigma_day_val is not None and sigma_day_val != 0.0) else None
                mfe_sigma = round(mfe / sigma_day_val, 6) if (sigma_day_val is not None and sigma_day_val != 0.0) else None
                mae_ibr = round(mae / ib_range_val, 6) if (ib_range_val is not None and ib_range_val != 0.0) else None
                mfe_ibr = round(mfe / ib_range_val, 6) if (ib_range_val is not None and ib_range_val != 0.0) else None

                close_price = float(window_bars["close"].iloc[-1])
                if is_short:
                    close_return = (entry_price - close_price) / sigma_day_val if (sigma_day_val is not None and sigma_day_val != 0.0) else None
                else:
                    close_return = (close_price - entry_price) / sigma_day_val if (sigma_day_val is not None and sigma_day_val != 0.0) else None
                close_return = round(close_return, 6) if close_return is not None else None

                fp_statuses = {}
                fp_timestamps = {}
                for thresh in FP_THRESHOLDS:
                    if sigma_day_val is None:
                        fp_statuses[thresh] = "INCOMPLETE"
                        fp_timestamps[thresh] = None
                        continue
                    thresh_pts = thresh * sigma_day_val
                    if is_short:
                        fav_price = entry_price - thresh_pts
                        adv_price = entry_price + thresh_pts
                    else:
                        fav_price = entry_price + thresh_pts
                        adv_price = entry_price - thresh_pts

                    fav_idx = None
                    adv_idx = None
                    for i_, bar in window_bars.iterrows():
                        if is_short:
                            fav_hit = float(bar["low"]) <= fav_price
                            adv_hit = float(bar["high"]) >= adv_price
                        else:
                            fav_hit = float(bar["high"]) >= fav_price
                            adv_hit = float(bar["low"]) <= adv_price
                        if fav_idx is None and fav_hit:
                            fav_idx = i_
                        if adv_idx is None and adv_hit:
                            adv_idx = i_

                    if fav_idx is not None and adv_idx is not None:
                        if fav_idx == adv_idx:
                            fp_statuses[thresh] = "AMBIGUOUS"
                            fp_timestamps[thresh] = str(window_bars.loc[fav_idx, "ny_time"])
                        elif window_bars.index.get_loc(fav_idx) < window_bars.index.get_loc(adv_idx):
                            fp_statuses[thresh] = "FAVORABLE_FIRST"
                            fp_timestamps[thresh] = str(window_bars.loc[fav_idx, "ny_time"])
                        else:
                            fp_statuses[thresh] = "ADVERSE_FIRST"
                            fp_timestamps[thresh] = str(window_bars.loc[adv_idx, "ny_time"])
                    elif fav_idx is not None:
                        fp_statuses[thresh] = "FAVORABLE_FIRST"
                        fp_timestamps[thresh] = str(window_bars.loc[fav_idx, "ny_time"])
                    elif adv_idx is not None:
                        fp_statuses[thresh] = "ADVERSE_FIRST"
                        fp_timestamps[thresh] = str(window_bars.loc[adv_idx, "ny_time"])
                    else:
                        fp_statuses[thresh] = "NOT_REACHED"
                        fp_timestamps[thresh] = None

                actual_last_ts = str(window_bars["ny_time"].iloc[-1])

                rows_list.append({
                    "touch_id": tr["touch_id"],
                    "config_id": tr["config_id"],
                    "level_direction": tr["level_direction"],
                    "touch_direction": tr["touch_direction"],
                    "horizon": horizon_name,
                    "label_status": "COMPLETE",
                    "label_start": str(label_start),
                    "requested_end_exclusive": str(requested_end),
                    "actual_last_bar": actual_last_ts,
                    "required_bar_count": required,
                    "actual_bar_count": actual_count,
                    "mae": mae,
                    "mfe": mfe,
                    "mae_sigma_ratio": mae_sigma,
                    "mfe_sigma_ratio": mfe_sigma,
                    "mae_ib_range_ratio": mae_ibr,
                    "mfe_ib_range_ratio": mfe_ibr,
                    "directional_horizon_close_return_sigma": close_return,
                    "sigma_day": sigma_day_val,
                    "fp_025_sigma": fp_statuses[0.25],
                    "fp_050_sigma": fp_statuses[0.50],
                    "fp_075_sigma": fp_statuses[0.75],
                    "fp_100_sigma": fp_statuses[1.00],
                    "fp_025_timestamp": fp_timestamps[0.25],
                    "fp_050_timestamp": fp_timestamps[0.50],
                    "fp_075_timestamp": fp_timestamps[0.75],
                    "fp_100_timestamp": fp_timestamps[1.00],
                })

        if not rows_list:
            return pd.DataFrame(columns=VIXLevelEngine.EXCURSION_COLUMNS)
        return pd.DataFrame(rows_list)

    @staticmethod
    def assign_overlap_clusters(
        touches_df: pd.DataFrame,
    ) -> pd.DataFrame:
        if touches_df.empty:
            return touches_df.copy()
        df = touches_df.copy()
        df = df.sort_values(["touch_bar_timestamp", "level_id"])

        cluster_ids = []
        current_cluster = 0
        current_end = None

        for _, tr in df.iterrows():
            touch_ts = pd.Timestamp(tr["touch_bar_timestamp"])
            session = tr["session_touched"]
            start = touch_ts + pd.Timedelta(minutes=1)
            end = pd.Timestamp(f"{session} 16:00", tz=NY_TZ)

            if start >= end:
                cluster_ids.append(0)
                continue

            if current_end is not None and start < current_end:
                cluster_ids.append(current_cluster)
                current_end = max(current_end, end)
            else:
                current_cluster += 1
                cluster_ids.append(current_cluster)
                current_end = end

        df["overlap_cluster_id"] = cluster_ids
        return df
