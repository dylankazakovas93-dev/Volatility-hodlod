"""Stage 1: Deterministic ES/VIX level-generation, touch-detection, excursion
engine for a single preregistered grid configuration.

Every public method is deterministic (no RNG, stable ordering).
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

TRADING_DAYS = 252.0
RTH_START = "09:30"
RTH_END = "16:00"
NY_TZ = "America/New_York"
LEVEL_NAMESPACE = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


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
    rth["ny_time"] = ny[rth.index]
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


def _generate_level_id(config_id: str, session_date: str, direction: str) -> str:
    raw = f"{config_id}_{session_date}_{direction}"
    return str(uuid.uuid5(LEVEL_NAMESPACE, raw))


def _generate_touch_id(level_id: str, bar_ts: str) -> str:
    raw = f"{level_id}_{bar_ts}"
    return str(uuid.uuid5(LEVEL_NAMESPACE, raw))


class VIXLevelEngine:
    """Deterministic level generation and touch detection for one config."""

    LEVEL_COLUMNS = [
        "level_id", "config_id", "session_date", "direction",
        "level_price", "cash_open", "vix_close", "vix_source_date",
        "sigma_day", "sigma_multiplier", "imp_up", "imp_dn",
        "ib_high", "ib_low", "ib_range", "ib_ext_up", "ib_ext_dn",
        "sigma_offset", "offset_family", "offset_parameter",
        "offset_value", "created_at", "ib_minutes",
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
            cash_open = float(session_bars["open"].iloc[0])
            prior_vix = _prior_vix_close(vix_df, sd)
            if prior_vix is None:
                continue
            vix_src_date = _vix_source_date(vix_df, sd)

            sigma_day = cash_open * (prior_vix / 100.0) / math.sqrt(TRADING_DAYS)
            imp_up = cash_open + self.config.sigma_multiplier * sigma_day
            imp_dn = cash_open - self.config.sigma_multiplier * sigma_day

            ib_count = self.config.ib_minutes
            ib_bars = session_bars.iloc[:ib_count]
            if ib_bars.empty:
                continue
            ib_high = float(ib_bars["high"].max())
            ib_low = float(ib_bars["low"].min())
            ib_range = ib_high - ib_low
            ib_ext_up = ib_high + ib_range
            ib_ext_dn = ib_low - ib_range

            if self.config.offset_family == "fixed":
                sigma_offset = float(self.config.offset_value)
            else:
                sigma_offset = sigma_day * self.config.offset_value

            upper_level = (ib_ext_up + imp_up) / 2.0 - sigma_offset
            lower_level = (ib_ext_dn + imp_dn) / 2.0 + sigma_offset

            created_bar = ib_bars.iloc[-1]
            created_at = str(created_bar["ny_time"])

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
                    "created_at": created_at,
                    "ib_minutes": self.config.ib_minutes,
                })

        if not rows:
            return pd.DataFrame(columns=VIXLevelEngine.LEVEL_COLUMNS)
        return pd.DataFrame(rows)
    
    TOUCH_COLUMNS = [
        "touch_id", "level_id", "config_id", "level_direction",
        "touch_direction", "level_price", "touch_bar_timestamp",
        "touch_bar_open", "touch_bar_high", "touch_bar_low",
        "reference_entry_price", "touch_type", "gap_through",
        "session_created", "session_touched",
    ]

    @staticmethod
    def detect_touches(
        levels_df: pd.DataFrame, es_df: pd.DataFrame
    ) -> pd.DataFrame:
        rows = []
        rth = _rth_bars(es_df)
        session_dates = sorted(rth["session_date"].unique())

        level_records = levels_df.to_dict("records")
        rth_by_session = {
            sd: grp.sort_values("ny_time")
            for sd, grp in rth.groupby("session_date")
        }

        for lr in level_records:
            session_idx = session_dates.index(lr["session_date"])
            max_session_idx = min(
                session_idx + 20, len(session_dates)
            )
            created_ny = pd.Timestamp(lr["created_at"])
            level_price = lr["level_price"]
            is_upper = lr["direction"] == "UPPER"

            touched = None
            for si in range(session_idx, max_session_idx):
                sd = session_dates[si]
                sb = rth_by_session.get(sd)
                if sb is None or sb.empty:
                    continue
                for _, bar in sb.iterrows():
                    bar_ts = bar["ny_time"]
                    if bar_ts <= created_ny:
                        continue
                    bar_open = float(bar["open"])
                    bar_high = float(bar["high"])
                    bar_low = float(bar["low"])

                    if is_upper:
                        if bar_high >= level_price:
                            gap = bar_low > level_price
                            ref_price = bar_open if gap else level_price
                            touch_type = "GAP_THROUGH" if gap else "CLEAN"
                        else:
                            continue
                    else:
                        if bar_low <= level_price:
                            gap = bar_high < level_price
                            ref_price = bar_open if gap else level_price
                            touch_type = "GAP_THROUGH" if gap else "CLEAN"
                        else:
                            continue

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
                        "touch_type": touch_type,
                        "gap_through": gap,
                        "session_created": lr["session_date"],
                        "session_touched": sd,
                    }
                    break
                if touched is not None:
                    break

            if touched is None:
                continue

            rows.append(touched)

        if not rows:
            return pd.DataFrame(columns=VIXLevelEngine.TOUCH_COLUMNS)
        return pd.DataFrame(rows)

    EXCURSION_COLUMNS = [
        "touch_id", "config_id", "level_direction", "touch_direction",
        "horizon", "horizon_minutes", "mae", "mfe",
        "start_timestamp", "end_timestamp", "first_passage",
    ]

    @staticmethod
    def compute_excursions(
        touches_df: pd.DataFrame, es_df: pd.DataFrame
    ) -> pd.DataFrame:
        if touches_df.empty:
            return pd.DataFrame(columns=VIXLevelEngine.EXCURSION_COLUMNS)
        rows = []
        rth = _rth_bars(es_df)
        rth_by_session = {
            sd: grp.sort_values("ny_time")
            for sd, grp in rth.groupby("session_date")
        }
        session_dates = sorted(rth["session_date"].unique())

        horizons = [
            ("15min", 15),
            ("30min", 30),
            ("60min", 60),
            ("120min", 120),
            ("RTH_REMAINDER", None),
        ]

        for _, tr in touches_df.iterrows():
            touch_ts = pd.Timestamp(tr["touch_bar_timestamp"])
            touch_session = tr["session_touched"]
            entry_price = tr["reference_entry_price"]
            is_short = tr["touch_direction"] == "SHORT"
            session_idx = session_dates.index(touch_session)

            for h_name, h_mins in horizons:
                label_start = touch_ts + pd.Timedelta(minutes=1)
                if h_mins is not None:
                    label_end = label_start + pd.Timedelta(minutes=h_mins)
                else:
                    label_end = None

                future_bars = []
                for si in range(session_idx, len(session_dates)):
                    sb = rth_by_session.get(session_dates[si])
                    if sb is None or sb.empty:
                        continue
                    for _, bar in sb.iterrows():
                        bt = bar["ny_time"]
                        if bt < label_start:
                            continue
                        if label_end is not None and bt >= label_end:
                            break
                        future_bars.append(bar)
                    if label_end is not None:
                        last_bar_ts = sb["ny_time"].iloc[-1]
                        if last_bar_ts >= label_end:
                            break

                if not future_bars:
                    continue

                fut_df = pd.DataFrame(future_bars)
                fut_high = float(fut_df["high"].max())
                fut_low = float(fut_df["low"].min())

                if is_short:
                    mfe = entry_price - fut_low
                    mae = fut_high - entry_price
                else:
                    mfe = fut_high - entry_price
                    mae = entry_price - fut_low

                mfe = round(max(0.0, mfe), 6)
                mae = round(max(0.0, mae), 6)

                fav_bar_idx = None
                adv_bar_idx = None
                for i, bar in enumerate(future_bars):
                    if is_short:
                        fav = float(bar["low"]) <= entry_price
                        adv = float(bar["high"]) >= entry_price
                    else:
                        fav = float(bar["high"]) >= entry_price
                        adv = float(bar["low"]) <= entry_price
                    if fav_bar_idx is None and fav:
                        fav_bar_idx = i
                    if adv_bar_idx is None and adv:
                        adv_bar_idx = i

                if fav_bar_idx is not None and adv_bar_idx is not None:
                    if fav_bar_idx < adv_bar_idx:
                        first_passage = "FAVORABLE_FIRST"
                    elif adv_bar_idx < fav_bar_idx:
                        first_passage = "ADVERSE_FIRST"
                    else:
                        first_passage = "AMBIGUOUS"
                elif fav_bar_idx is not None:
                    first_passage = "FAVORABLE_FIRST"
                elif adv_bar_idx is not None:
                    first_passage = "ADVERSE_FIRST"
                else:
                    first_passage = "NOT_REACHED"

                end_ts = str(future_bars[-1]["ny_time"]) if future_bars else None

                rows.append({
                    "touch_id": tr["touch_id"],
                    "config_id": tr["config_id"],
                    "level_direction": tr["level_direction"],
                    "touch_direction": tr["touch_direction"],
                    "horizon": h_name,
                    "horizon_minutes": h_mins,
                    "mae": mae,
                    "mfe": mfe,
                    "start_timestamp": str(label_start),
                    "end_timestamp": end_ts,
                    "first_passage": first_passage,
                })

        if not rows:
            return pd.DataFrame(columns=VIXLevelEngine.EXCURSION_COLUMNS)
        return pd.DataFrame(rows)

    @staticmethod
    def assign_overlap_clusters(
        touches_df: pd.DataFrame,
    ) -> pd.DataFrame:
        if touches_df.empty:
            return touches_df.copy()
        df = touches_df.copy()
        df = df.sort_values(["touch_bar_timestamp", "level_id"])
        clusters = []
        cluster_id = 1
        prev_end = None

        for _, tr in df.iterrows():
            touch_ts = pd.Timestamp(tr["touch_bar_timestamp"])
            window_end = touch_ts + pd.Timedelta(days=1)
            if prev_end is not None and touch_ts < prev_end:
                clusters.append(cluster_id)
                prev_end = max(prev_end, window_end)
            else:
                cluster_id += 1
                clusters.append(cluster_id)
                prev_end = window_end

        df["overlap_cluster_id"] = clusters
        return df
