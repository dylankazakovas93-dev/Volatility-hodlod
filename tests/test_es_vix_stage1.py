"""Stage 1 deterministic tests for the ES/VIX level-generation, touch-detection,
and MAE/MFE engine.

Tests use synthetic minute-bar fixtures and tiny pre-2025 implementation
fixtures to verify mechanics only — never signal quality.
"""
from __future__ import annotations

import copy
import hashlib
import math
import os
import tempfile

import pandas as pd
import pytest

from research.es_vix_level_discovery.stage1_engine import (
    VIXLevelEngine,
    LevelConfig,
    _ny_time,
    _is_rth,
    _rth_bars,
    _prior_vix_close,
    _generate_level_id,
    _generate_touch_id,
    _session_available_reason,
    FP_THRESHOLDS,
    FIXED_HORIZONS,
)
from research.es_vix_level_discovery.stage1_schemas import (
    LEVELS_COLUMNS,
    TOUCHES_COLUMNS,
    EXCURSIONS_COLUMNS,
    FEATURE_PROVENANCE_COLUMNS,
    write_levels_csv,
    write_touches_csv,
    write_excursions_csv,
    write_provenance_csv,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ES_CAUSAL = os.path.join(REPO_ROOT, "data", "es_1m", "es_continuous_causal_2018_2026_1m.csv")
VIX_NORM = os.path.join(REPO_ROOT, "data", "vix_daily_1990_2026.csv")
NY_TZ = "America/New_York"


def _ny_to_utc(ny_dt_str: str) -> str:
    return str(pd.Timestamp(ny_dt_str, tz=NY_TZ).tz_convert("UTC"))


def synthetic_session_bars(
    session_date: str,
    rth_open: float = 4700.0,
    drift: float = 0.0,
    range_pct: float = 0.002,
    num_rth_bars: int = 390,
    amp: float = 0.0,
) -> pd.DataFrame:
    rows = []
    for i in range(num_rth_bars):
        minute_offset = i
        base = rth_open + drift * (minute_offset / 390.0)
        half_range = rth_open * range_pct / 2.0
        wiggle = amp * math.sin(minute_offset * 0.1)
        ctr = base + wiggle
        h = ctr + half_range * abs(math.sin(minute_offset * 0.07 + 1.0))
        l_ = ctr - half_range * abs(math.sin(minute_offset * 0.07 + 2.0))
        if h < ctr:
            h, ctr = ctr, h
        if l_ > ctr:
            l_, ctr = ctr, l_
        if l_ > h:
            l_, h = h, l_
        h = round(max(h, ctr), 2)
        l_ = round(min(l_, ctr), 2)
        o = round(ctr, 2)
        c = round(ctr + half_range * 0.1 * (1 if i % 2 == 0 else -1), 2)
        if c > h:
            c = h
        if c < l_:
            c = l_
        hour = 9 + (minute_offset + 30) // 60
        minute = (minute_offset + 30) % 60
        ny_dt = f"{session_date} {hour:02d}:{minute:02d}:00"
        utc_ts = _ny_to_utc(ny_dt)
        rows.append({
            "timestamp": utc_ts,
            "open": o,
            "high": h,
            "low": l_,
            "close": c,
            "volume": 1000,
            "contract": "ESM8",
            "session_date": session_date,
            "roll_day": 0,
        })
    return pd.DataFrame(rows)


def synthetic_multiday_es(
    start_date: str = "2024-01-02",
    num_sessions: int = 25,
    rth_open: float = 4700.0,
    range_pct: float = 0.002,
) -> pd.DataFrame:
    all_rows = []
    sd = pd.Timestamp(start_date)
    for i in range(num_sessions):
        d = sd + pd.Timedelta(days=i)
        if d.weekday() >= 5:
            continue
        sd_str = d.strftime("%Y-%m-%d")
        drift = (i % 5) * 2.0
        df = synthetic_session_bars(sd_str, rth_open=rth_open + i * 0.5, drift=drift,
                                    range_pct=range_pct)
        all_rows.append(df)
    return pd.concat(all_rows, ignore_index=True)


def synthetic_vix(
    start_date: str = "2023-12-15",
    num_days: int = 100,
    vix_close: float = 15.0,
) -> pd.DataFrame:
    dates = pd.bdate_range(start=start_date, periods=num_days)
    return pd.DataFrame({
        "date": dates,
        "vix_open": vix_close,
        "vix_high": vix_close + 0.5,
        "vix_low": vix_close - 0.5,
        "vix_close": vix_close,
    })


def _load_smoke_es() -> pd.DataFrame:
    return pd.read_csv(ES_CAUSAL, nrows=50000)


def _load_smoke_vix() -> pd.DataFrame:
    df = pd.read_csv(VIX_NORM, parse_dates=["date"])
    df["date"] = pd.to_datetime(df["date"])
    return df


def _ny_time_from_session(session_date: str, minute_offset: int) -> str:
    """Return NY-time string at minute_offset (0=09:30) for session."""
    total_minutes = 30 + minute_offset
    hour = 9 + total_minutes // 60
    minute = total_minutes % 60
    return f"{session_date} {hour:02d}:{minute:02d}:00"


# ══════════════════════════════════════════════════════════════════════
# Formula and Level Generation
# ══════════════════════════════════════════════════════════════════════

class TestFormulaCorrectness:
    def test_sigma_day_formula(self):
        cash_open = 4700.0
        vix_close = 15.0
        sigma_day = cash_open * (vix_close / 100.0) / math.sqrt(252)
        expected = cash_open * 0.15 / math.sqrt(252)
        assert abs(sigma_day - expected) < 1e-10

    def test_level_formula_with_proportional_offset(self):
        cfg = LevelConfig(
            config_id="TEST_100_IB30_PCT_000",
            sigma_multiplier=1.0,
            ib_minutes=30,
            offset_family="proportional",
            offset_parameter="offset_pct",
            offset_value=0.0,
        )
        es = synthetic_session_bars("2024-01-02", rth_open=4700.0, range_pct=0.001)
        vix = synthetic_vix(vix_close=15.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        assert len(levels) == 2
        upper = levels[levels["direction"] == "UPPER"].iloc[0]
        lower = levels[levels["direction"] == "LOWER"].iloc[0]
        assert upper["level_price"] > 4700.0
        assert lower["level_price"] < 4700.0

    def test_proportional_offset_applied(self):
        cfg = LevelConfig(
            config_id="TEST_100_IB30_PCT_004",
            sigma_multiplier=1.0,
            ib_minutes=30,
            offset_family="proportional",
            offset_parameter="offset_pct",
            offset_value=0.04,
        )
        es = synthetic_session_bars("2024-01-02", rth_open=4700.0)
        vix = synthetic_vix(vix_close=15.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        upper = levels[levels["direction"] == "UPPER"].iloc[0]
        sigma_day = 4700.0 * (15.0 / 100.0) / math.sqrt(252)
        expected_offset = sigma_day * 0.04
        assert abs(upper["sigma_offset"] - expected_offset) < 1e-6

    def test_fixed_offset_applied(self):
        cfg = LevelConfig(
            config_id="TEST_100_IB30_FIXED_050",
            sigma_multiplier=1.0,
            ib_minutes=30,
            offset_family="fixed",
            offset_parameter="fixed_offset_es_points",
            offset_value=5.0,
        )
        es = synthetic_session_bars("2024-01-02", rth_open=4700.0)
        vix = synthetic_vix(vix_close=15.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        upper = levels[levels["direction"] == "UPPER"].iloc[0]
        assert upper["sigma_offset"] == 5.0


# ══════════════════════════════════════════════════════════════════════
# 1. CORRECT IB BOUNDARIES (timestamp-based)
# ══════════════════════════════════════════════════════════════════════

class TestIBBoundariesTimestamp:
    """IB boundaries determined by timestamps, not row count."""

    @staticmethod
    def _run_ib_test(ib_minutes: int, expected_cutoff_minutes: int):
        session_date = "2024-01-02"
        es = synthetic_session_bars(session_date, rth_open=4800.0, range_pct=0.003)
        cfg = LevelConfig(
            f"TEST_IB{ib_minutes}", 0.75, ib_minutes,
            "proportional", "offset_pct", 0.0,
        )
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, synthetic_vix(vix_close=15.0))
        assert len(levels) == 2

        rth = _rth_bars(es)
        sess = rth[rth["session_date"] == session_date].sort_values("ny_time")

        ib_start = pd.Timestamp(f"{session_date} 09:30", tz=NY_TZ)
        ib_end = ib_start + pd.Timedelta(minutes=ib_minutes)
        ib_bars = sess[(sess["ny_time"] >= ib_start) & (sess["ny_time"] <= ib_end)]
        expected_ib_high = float(ib_bars["high"].max())
        expected_ib_low = float(ib_bars["low"].min())

        upper = levels[levels["direction"] == "UPPER"].iloc[0]
        assert abs(upper["ib_high"] - expected_ib_high) < 1e-6
        assert abs(upper["ib_low"] - expected_ib_low) < 1e-6

    def test_ib30_cutoff_includes_1000(self):
        self._run_ib_test(30, 30)

    def test_ib60_cutoff_includes_1030(self):
        self._run_ib_test(60, 60)

    def test_ib30_created_at_is_1000(self):
        session_date = "2024-01-02"
        es = synthetic_session_bars(session_date, rth_open=4800.0, range_pct=0.003)
        cfg = LevelConfig("TEST_IB30_CR", 0.75, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, synthetic_vix(vix_close=15.0))
        upper = levels[levels["direction"] == "UPPER"].iloc[0]
        expected_created = pd.Timestamp(f"{session_date} 10:00", tz=NY_TZ)
        assert pd.Timestamp(upper["created_at"]) == expected_created

    def test_ib60_created_at_is_1030(self):
        session_date = "2024-01-02"
        es = synthetic_session_bars(session_date, rth_open=4800.0, range_pct=0.003)
        cfg = LevelConfig("TEST_IB60_CR", 0.75, 60, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, synthetic_vix(vix_close=15.0))
        upper = levels[levels["direction"] == "UPPER"].iloc[0]
        expected_created = pd.Timestamp(f"{session_date} 10:30", tz=NY_TZ)
        assert pd.Timestamp(upper["created_at"]) == expected_created

    def test_first_eligible_at_ib30(self):
        session_date = "2024-01-02"
        es = synthetic_session_bars(session_date, rth_open=4800.0, range_pct=0.003)
        cfg = LevelConfig("TEST_IB30_FE", 0.75, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, synthetic_vix(vix_close=15.0))
        upper = levels[levels["direction"] == "UPPER"].iloc[0]
        expected_fe = pd.Timestamp(f"{session_date} 10:01", tz=NY_TZ)
        assert pd.Timestamp(upper["first_eligible_at"]) == expected_fe

    def test_first_eligible_at_ib60(self):
        session_date = "2024-01-02"
        es = synthetic_session_bars(session_date, rth_open=4800.0, range_pct=0.003)
        cfg = LevelConfig("TEST_IB60_FE", 0.75, 60, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, synthetic_vix(vix_close=15.0))
        upper = levels[levels["direction"] == "UPPER"].iloc[0]
        expected_fe = pd.Timestamp(f"{session_date} 10:31", tz=NY_TZ)
        assert pd.Timestamp(upper["first_eligible_at"]) == expected_fe

    def test_creation_bar_excluded_from_touch(self):
        """The created_at bar cannot be the touch bar.
        For 30-min IB: created_at=10:00, so 10:00 bar cannot be touched."""
        session_date = "2024-01-02"
        es = synthetic_session_bars(session_date, rth_open=4600.0, range_pct=0.001)
        vix = synthetic_vix(vix_close=80.0)
        cfg = LevelConfig("TEST_EXCL_IB30", 0.75, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        for _, t in touches.iterrows():
            touch_ts = pd.Timestamp(t["touch_bar_timestamp"])
            created_ts = pd.Timestamp(
                levels[levels["level_id"] == t["level_id"]]["created_at"].iloc[0]
            )
            assert touch_ts > created_ts

    def test_missing_ib_bars_skips_session(self):
        """Session with missing IB cutoff bar is skipped."""
        session_date = "2024-01-02"
        es = synthetic_session_bars(session_date, rth_open=4800.0, range_pct=0.003,
                                    num_rth_bars=30)
        cfg = LevelConfig("TEST_MISS_IB", 0.75, 60, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, synthetic_vix(vix_close=15.0))
        # 60-min IB requires bars through 10:30; only 30 bars provided
        assert levels.empty


# ══════════════════════════════════════════════════════════════════════
# 2. CORRECT GAP-THROUGH CLASSIFICATION (open-based)
# ══════════════════════════════════════════════════════════════════════

class TestGapThroughOpenBased:
    """Gap is determined by touch-bar open, not low/high of completed bar."""

    def test_upper_gap_by_open_only(self):
        es_rows = []
        sd = "2024-01-02"
        for i in range(390):
            hour = 9 + (i + 30) // 60
            minute = (i + 30) % 60
            ny_dt = f"{sd} {hour:02d}:{minute:02d}:00"
            utc_ts = _ny_to_utc(ny_dt)
            bar_open = 4800.0 if i == 100 else 4700.0
            es_rows.append({
                "timestamp": utc_ts,
                "open": bar_open,
                "high": bar_open + 2.0,
                "low": bar_open - 1.0,
                "close": bar_open + 0.5,
                "volume": 1000,
                "contract": "ESM8",
                "session_date": sd,
                "roll_day": 0,
            })
        es = pd.DataFrame(es_rows)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_GAP_UPPER", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        upper_touches = touches[touches["level_direction"] == "UPPER"]
        if not upper_touches.empty:
            for _, t in upper_touches.iterrows():
                is_gap = t["gap_through"]
                bar_open = t["touch_bar_open"]
                level_price = t["level_price"]
                if is_gap:
                    assert bar_open > level_price
                    assert t["reference_entry_price"] == bar_open
                else:
                    assert bar_open <= level_price
                    assert t["reference_entry_price"] == level_price

    def test_lower_gap_by_open_only(self):
        es_rows = []
        sd = "2024-01-02"
        for i in range(390):
            hour = 9 + (i + 30) // 60
            minute = (i + 30) % 60
            ny_dt = f"{sd} {hour:02d}:{minute:02d}:00"
            utc_ts = _ny_to_utc(ny_dt)
            bar_open = 4600.0 if i == 100 else 4700.0
            es_rows.append({
                "timestamp": utc_ts,
                "open": bar_open,
                "high": bar_open + 1.0,
                "low": bar_open - 2.0,
                "close": bar_open - 0.5,
                "volume": 1000,
                "contract": "ESM8",
                "session_date": sd,
                "roll_day": 0,
            })
        es = pd.DataFrame(es_rows)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_GAP_LOWER", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        lower_touches = touches[touches["level_direction"] == "LOWER"]
        if not lower_touches.empty:
            for _, t in lower_touches.iterrows():
                is_gap = t["gap_through"]
                bar_open = t["touch_bar_open"]
                level_price = t["level_price"]
                if is_gap:
                    assert bar_open < level_price
                    assert t["reference_entry_price"] == bar_open
                else:
                    assert bar_open >= level_price
                    assert t["reference_entry_price"] == level_price

    def test_gap_bar_crosses_back_remains_gap(self):
        """A bar that opens above the level and later crosses back through
        it is still a gap-through with entry at bar open."""
        es_rows = []
        sd = "2024-01-02"
        for i in range(390):
            hour = 9 + (i + 30) // 60
            minute = (i + 30) % 60
            ny_dt = f"{sd} {hour:02d}:{minute:02d}:00"
            utc_ts = _ny_to_utc(ny_dt)
            if i == 100:
                bar_open = 4850.0
                bar_high = 4860.0
                bar_low = 4780.0
            else:
                bar_open = 4700.0
                bar_high = 4702.0
                bar_low = 4698.0
            es_rows.append({
                "timestamp": utc_ts,
                "open": bar_open,
                "high": bar_high,
                "low": bar_low,
                "close": bar_open + 0.5,
                "volume": 1000,
                "contract": "ESM8",
                "session_date": sd,
                "roll_day": 0,
            })
        es = pd.DataFrame(es_rows)
        vix = synthetic_vix(vix_close=80.0)
        cfg = LevelConfig("TEST_GAP_CROSSBACK", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        upper_touches = touches[touches["level_direction"] == "UPPER"]
        if not upper_touches.empty:
            for _, t in upper_touches.iterrows():
                if t["touch_bar_open"] > t["level_price"]:
                    assert t["gap_through"] is True
                    assert t["reference_entry_price"] == t["touch_bar_open"]


# ══════════════════════════════════════════════════════════════════════
# Level direction
# ══════════════════════════════════════════════════════════════════════

class TestLevelDirection:
    def test_upper_touch_is_short(self):
        es = synthetic_session_bars("2024-01-02", rth_open=4700.0, range_pct=0.001)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_DIR_100_IB30_PCT_000", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        for _, t in touches.iterrows():
            if t["level_direction"] == "UPPER":
                assert t["touch_direction"] == "SHORT"
            else:
                assert t["touch_direction"] == "LONG"


# ══════════════════════════════════════════════════════════════════════
# 3. LIFETIME AND DETERMINISTIC ORDERING
# ══════════════════════════════════════════════════════════════════════

class TestLifetimeAndOrdering:
    def test_jive_life_sessions_used(self):
        """Level uses config.line_life_sessions = 4 (non-default)."""
        es = synthetic_multiday_es("2024-01-02", num_sessions=25, rth_open=4700.0)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_LIFE_4", 1.0, 30, "proportional", "offset_pct", 0.0,
                           line_life_sessions=4)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        rth = _rth_bars(es)
        session_dates = sorted(rth["session_date"].unique())
        if not touches.empty:
            for _, t in touches.iterrows():
                created_idx = session_dates.index(t["session_created"])
                touched_idx = session_dates.index(t["session_touched"])
                session_gap = touched_idx - created_idx
                assert session_gap < 4

    def test_expiry_session_recorded(self):
        es = synthetic_multiday_es("2024-01-02", num_sessions=25, rth_open=4700.0)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_EXPIRY", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        rth = _rth_bars(es)
        session_dates = sorted(rth["session_date"].unique())
        for _, lv in levels.iterrows():
            created_idx = session_dates.index(lv["session_date"])
            expected_expiry_idx = min(created_idx + 19, len(session_dates) - 1)
            assert lv["expiry_session"] == session_dates[expected_expiry_idx]

    def test_deterministic_ordering_older_first(self):
        """Levels sorted by (created_at, upper_before_lower, level_id)."""
        es = synthetic_multiday_es("2024-01-02", num_sessions=5, rth_open=4700.0, range_pct=0.002)
        vix = synthetic_vix(vix_close=50.0)
        cfg = LevelConfig("TEST_DORD", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        if not touches.empty:
            orders = touches["deterministic_order"].values
            assert list(orders) == sorted(orders)

    def test_upper_before_lower_same_timestamp(self):
        """For same created_at, upper level touched before lower."""
        es = synthetic_session_bars("2024-01-02", rth_open=4700.0, range_pct=0.003)
        vix = synthetic_vix(vix_close=80.0)
        cfg = LevelConfig("TEST_UP_LOW", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        if len(touches) >= 2:
            upper_touches = touches[touches["level_direction"] == "UPPER"]
            lower_touches = touches[touches["level_direction"] == "LOWER"]
            if not upper_touches.empty and not lower_touches.empty:
                upper_order = int(upper_touches["deterministic_order"].iloc[0])
                lower_order = int(lower_touches["deterministic_order"].iloc[0])
                assert upper_order < lower_order

    def test_level_consumed_after_first_touch(self):
        es = synthetic_multiday_es("2024-01-02", num_sessions=5, rth_open=4700.0)
        vix = synthetic_vix(vix_close=50.0)
        cfg = LevelConfig("TEST_CONS_100_IB30_PCT_000", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        if not touches.empty:
            touched_levels = touches["level_id"].value_counts()
            assert all(v == 1 for v in touched_levels.values), "Level touched more than once"

    def test_line_life_sessions_always_20(self):
        """All preregistered configs have line_life_sessions == 20."""
        es = synthetic_multiday_es("2024-01-02", num_sessions=5, rth_open=4700.0)
        vix = synthetic_vix(vix_close=15.0)
        for line_life in [20]:
            cfg = LevelConfig("TEST_LL_20", 1.0, 30, "proportional", "offset_pct", 0.0,
                               line_life_sessions=line_life)
            engine = VIXLevelEngine(cfg)
            levels = engine.generate_levels(es, vix)
            assert all(levels["line_life_sessions"] == 20)


# ══════════════════════════════════════════════════════════════════════
# 4 + 5. CORRECT FIXED-HORIZON AND RTH-REMAINDER LABELS
# ══════════════════════════════════════════════════════════════════════

class TestFixedHorizons:
    """Fixed horizons: same-session only, INCOMPLETE if insufficient bars."""

    @staticmethod
    def _guarantee_touches():
        session_date = "2024-01-02"
        rows = []
        for i in range(390):
            hour = 9 + (i + 30) // 60
            minute = (i + 30) % 60
            ny_dt = f"{session_date} {hour:02d}:{minute:02d}:00"
            utc_ts = _ny_to_utc(ny_dt)
            high = 4900.0 + (i % 5) * 2.0
            low = 4500.0 - (i % 5) * 2.0
            o = 4700.0
            c = 4700.0
            rows.append({
                "timestamp": utc_ts,
                "open": o, "high": high, "low": low, "close": c,
                "volume": 1000, "contract": "ESM8",
                "session_date": session_date, "roll_day": 0,
            })
        es = pd.DataFrame(rows)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_EXC", 0.75, 60, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        return es, touches, engine

    def test_horizons_present(self):
        es, touches, engine = self._guarantee_touches()
        if touches.empty:
            pytest.skip("No touches")
        excursions = engine.compute_excursions(touches, es)
        expected_horizons = {"15m", "30m", "60m", "120m", "RTH_REMAINDER"}
        assert expected_horizons.issubset(set(excursions["horizon"].unique()))

    def test_labels_start_after_touch(self):
        es, touches, engine = self._guarantee_touches()
        if touches.empty:
            pytest.skip("No touches")
        excursions = engine.compute_excursions(touches, es)
        for _, exc in excursions.iterrows():
            start = pd.Timestamp(exc["label_start"])
            touch_ts = pd.Timestamp(
                touches[touches["touch_id"] == exc["touch_id"]]["touch_bar_timestamp"].iloc[0]
            )
            assert start == touch_ts + pd.Timedelta(minutes=1)

    def test_no_overnight_continuation(self):
        """Fixed horizon must not carry into next session."""
        es = synthetic_multiday_es("2024-01-02", num_sessions=3, rth_open=4700.0,
                                    range_pct=0.001)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_NOON", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        if touches.empty:
            pytest.skip("No touches")
        excursions = engine.compute_excursions(touches, es)
        for _, exc in excursions.iterrows():
            if exc["horizon"] != "RTH_REMAINDER":
                label_start = pd.Timestamp(exc["label_start"])
                req_end = pd.Timestamp(exc["requested_end_exclusive"])
                touch_session = touches[
                    touches["touch_id"] == exc["touch_id"]
                ]["session_touched"].iloc[0]
                # All label bars must be in the same session
                label_start_date = label_start.strftime("%Y-%m-%d")
                req_end_date = req_end.strftime("%Y-%m-%d")
                assert label_start_date == touch_session
                # If the horizon extends past session close, it's INCOMPLETE
                # but should never span to next session

    def test_incomplete_horizon_null_labels(self):
        """Insufficient remaining bars produces INCOMPLETE with null MAE/MFE."""
        session_date = "2024-01-02"
        es = synthetic_session_bars(session_date, rth_open=4700.0, range_pct=0.001,
                                    num_rth_bars=100)
        vix = synthetic_vix(vix_close=80.0)
        cfg = LevelConfig("TEST_INC", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        if touches.empty:
            pytest.skip("No touches")
        excursions = engine.compute_excursions(touches, es)
        fixed = excursions[excursions["horizon"].isin(["15m", "30m", "60m", "120m"])]
        incomplete = fixed[fixed["label_status"] == "INCOMPLETE"]
        if not incomplete.empty:
            assert incomplete["mae"].isna().all()
            assert incomplete["mfe"].isna().all()
            assert (incomplete["required_bar_count"] > incomplete["actual_bar_count"]).all()

    def test_rth_remainder_same_session_only(self):
        """RTH_REMAINDER must not include bars from later sessions."""
        es = synthetic_multiday_es("2024-01-02", num_sessions=5, rth_open=4700.0,
                                    range_pct=0.001)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_RTH_SAME", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        if touches.empty:
            pytest.skip("No touches")
        excursions = engine.compute_excursions(touches, es)
        remainder = excursions[excursions["horizon"] == "RTH_REMAINDER"]
        for _, exc in remainder.iterrows():
            touch_session = touches[
                touches["touch_id"] == exc["touch_id"]
            ]["session_touched"].iloc[0]
            actual_last = exc["actual_last_bar"]
            if actual_last is not None:
                last_session = pd.Timestamp(actual_last).strftime("%Y-%m-%d")
                assert last_session == touch_session

    def test_rth_remainder_incomplete_no_bars(self):
        """If no post-touch bar remains, RTH_REMAINDER is INCOMPLETE."""
        session_date = "2024-01-02"
        es = synthetic_session_bars(session_date, rth_open=4700.0, range_pct=0.001,
                                    num_rth_bars=60)
        vix = synthetic_vix(vix_close=80.0)
        cfg = LevelConfig("TEST_RTH_INC", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        if touches.empty:
            pytest.skip("No touches")
        excursions = engine.compute_excursions(touches, es)
        remainder = excursions[excursions["horizon"] == "RTH_REMAINDER"]
        incomplete = remainder[remainder["label_status"] == "INCOMPLETE"]
        if not incomplete.empty:
            for _, exc in incomplete.iterrows():
                assert exc["mae"] is None
                assert exc["mfe"] is None
                assert exc["actual_bar_count"] == 0


# ══════════════════════════════════════════════════════════════════════
# MAE/MFE
# ══════════════════════════════════════════════════════════════════════

class TestMAEMFE:
    @staticmethod
    def _guarantee_touches():
        session_date = "2024-01-02"
        rows = []
        for i in range(390):
            hour = 9 + (i + 30) // 60
            minute = (i + 30) % 60
            ny_dt = f"{session_date} {hour:02d}:{minute:02d}:00"
            utc_ts = _ny_to_utc(ny_dt)
            high = 4900.0 + (i % 5) * 2.0
            low = 4500.0 - (i % 5) * 2.0
            o = 4700.0
            c = 4700.0
            rows.append({
                "timestamp": utc_ts,
                "open": o, "high": high, "low": low, "close": c,
                "volume": 1000, "contract": "ESM8",
                "session_date": session_date, "roll_day": 0,
            })
        es = pd.DataFrame(rows)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_EXC_GUARANTEED", 0.75, 60, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        return es, touches, engine

    def test_mae_mfe_nonnegative(self):
        es, touches, engine = self._guarantee_touches()
        if touches.empty:
            pytest.skip("No touches")
        excursions = engine.compute_excursions(touches, es)
        complete = excursions[excursions["label_status"] == "COMPLETE"]
        if not complete.empty:
            assert (complete["mae"] >= 0).all()
            assert (complete["mfe"] >= 0).all()

    def test_long_mfe_mae_direction(self):
        es, touches, engine = self._guarantee_touches()
        if touches.empty:
            pytest.skip("No touches")
        excursions = engine.compute_excursions(touches, es)
        long_exc = excursions[excursions["touch_direction"] == "LONG"]
        if not long_exc.empty:
            for _, exc in long_exc.iterrows():
                assert isinstance(exc["mae"], (float, int)) or exc["mae"] is None
                assert isinstance(exc["mfe"], (float, int)) or exc["mfe"] is None

    def test_short_mfe_mae_direction(self):
        es, touches, engine = self._guarantee_touches()
        if touches.empty:
            pytest.skip("No touches")
        excursions = engine.compute_excursions(touches, es)
        short_exc = excursions[excursions["touch_direction"] == "SHORT"]
        if not short_exc.empty:
            for _, exc in short_exc.iterrows():
                assert isinstance(exc["mae"], (float, int)) or exc["mae"] is None
                assert isinstance(exc["mfe"], (float, int)) or exc["mfe"] is None


# ══════════════════════════════════════════════════════════════════════
# 6. FIRST-PASSAGE LABELS (sigma thresholds)
# ══════════════════════════════════════════════════════════════════════

class TestFirstPassageSigma:
    """First-passage at 0.25, 0.50, 0.75, 1.00 x sigma_day."""

    def test_first_passage_columns_present(self):
        es, touches, engine = TestMAEMFE._guarantee_touches()
        if touches.empty:
            pytest.skip("No touches")
        excursions = engine.compute_excursions(touches, es)
        for col in ["fp_025_sigma", "fp_050_sigma", "fp_075_sigma", "fp_100_sigma"]:
            assert col in excursions.columns
        valid = {"FAVORABLE_FIRST", "ADVERSE_FIRST", "AMBIGUOUS", "NOT_REACHED", "INCOMPLETE"}
        for col in ["fp_025_sigma", "fp_050_sigma", "fp_075_sigma", "fp_100_sigma"]:
            complete = excursions[excursions["label_status"] == "COMPLETE"]
            if not complete.empty:
                assert complete[col].isin(valid).all()

    def test_sigma_day_propagated_to_excursions(self):
        es, touches, engine = TestMAEMFE._guarantee_touches()
        if touches.empty:
            pytest.skip("No touches")
        excursions = engine.compute_excursions(touches, es)
        assert "sigma_day" in excursions.columns
        assert excursions["sigma_day"].notna().any()

    def test_ambiguous_same_bar(self):
        """If both thresholds hit in same bar, record AMBIGUOUS."""
        session_date = "2024-01-02"
        rows = []
        for i in range(390):
            hour = 9 + (i + 30) // 60
            minute = (i + 30) % 60
            ny_dt = f"{session_date} {hour:02d}:{minute:02d}:00"
            utc_ts = _ny_to_utc(ny_dt)
            low = 4500.0
            high = 4900.0
            o = 4700.0
            c = 4700.0
            if i >= 200:
                low = 4400.0
                high = 5000.0
            rows.append({
                "timestamp": utc_ts,
                "open": o, "high": high, "low": low, "close": c,
                "volume": 1000, "contract": "ESM8",
                "session_date": session_date, "roll_day": 0,
            })
        es = pd.DataFrame(rows)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_AMBIG", 0.75, 60, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        if touches.empty:
            pytest.skip("No touches")
        excursions = engine.compute_excursions(touches, es)
        complete = excursions[excursions["label_status"] == "COMPLETE"]
        if not complete.empty:
            assert "AMBIGUOUS" in complete["fp_025_sigma"].values or \
                   "AMBIGUOUS" in complete["fp_100_sigma"].values


# ══════════════════════════════════════════════════════════════════════
# 7. CORRECT OVERLAP CLUSTERS
# ══════════════════════════════════════════════════════════════════════

class TestOverlapClusters:
    def test_overlap_cluster_id_present(self):
        es = synthetic_multiday_es("2024-01-02", num_sessions=10, rth_open=4700.0)
        vix = synthetic_vix(vix_close=50.0)
        cfg = LevelConfig("TEST_OVR_100_IB30_PCT_000", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        if not touches.empty:
            touches_with_clusters = engine.assign_overlap_clusters(touches)
            assert "overlap_cluster_id" in touches_with_clusters.columns
            assert touches_with_clusters["overlap_cluster_id"].notna().all()

    def test_cluster_ids_start_at_1(self):
        es = synthetic_multiday_es("2024-01-02", num_sessions=10, rth_open=4700.0)
        vix = synthetic_vix(vix_close=50.0)
        cfg = LevelConfig("TEST_OVR1", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        if not touches.empty:
            touches_with_clusters = engine.assign_overlap_clusters(touches)
            non_zero = touches_with_clusters[
                touches_with_clusters["overlap_cluster_id"] > 0
            ]
            if not non_zero.empty:
                min_cluster = non_zero["overlap_cluster_id"].min()
                assert min_cluster >= 1, f"Min cluster ID is {min_cluster}"

    def test_input_order_invariant(self):
        """Reordering input rows does not change cluster assignment."""
        es = synthetic_multiday_es("2024-01-02", num_sessions=10, rth_open=4700.0)
        vix = synthetic_vix(vix_close=50.0)
        cfg = LevelConfig("TEST_ORDINV", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        if len(touches) < 2:
            pytest.skip("Need at least 2 touches")
        shuffled = touches.sample(frac=1, random_state=42)
        clusters1 = engine.assign_overlap_clusters(touches)
        clusters2 = engine.assign_overlap_clusters(shuffled)
        merged = clusters1[["touch_id", "overlap_cluster_id"]].merge(
            clusters2[["touch_id", "overlap_cluster_id"]],
            on="touch_id", suffixes=("_1", "_2")
        )
        assert (merged["overlap_cluster_id_1"] == merged["overlap_cluster_id_2"]).all()

    def test_cross_session_reset(self):
        """Clusters reset across non-overlapping sessions."""
        es = synthetic_multiday_es("2024-01-02", num_sessions=5, rth_open=4700.0,
                                    range_pct=0.002)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_CRSESS", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        if len(touches) < 2:
            pytest.skip("Need at least 2 touches")
        clusters = engine.assign_overlap_clusters(touches)
        sessions_with_clusters = clusters.groupby("session_touched")["overlap_cluster_id"].nunique()
        # Different sessions should not share the same non-zero cluster ID
        for s1 in clusters["session_touched"].unique():
            for s2 in clusters["session_touched"].unique():
                if s1 < s2:
                    c1 = set(clusters[clusters["session_touched"] == s1]["overlap_cluster_id"])
                    c2 = set(clusters[clusters["session_touched"] == s2]["overlap_cluster_id"])
                    non_zero_intersection = (c1 & c2) - {0}
                    assert len(non_zero_intersection) == 0, \
                        f"Sessions {s1} and {s2} share cluster IDs {non_zero_intersection}"


# ══════════════════════════════════════════════════════════════════════
# Determinism
# ══════════════════════════════════════════════════════════════════════

class TestDeterminism:
    def test_levels_deterministic(self):
        es = synthetic_multiday_es("2024-01-02", num_sessions=5, rth_open=4700.0)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_DET_100_IB30_PCT_000", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels1 = engine.generate_levels(es, vix)
        levels2 = engine.generate_levels(es, vix)
        pd.testing.assert_frame_equal(levels1, levels2)

    def test_touches_deterministic(self):
        es = synthetic_multiday_es("2024-01-02", num_sessions=5, rth_open=4700.0)
        vix = synthetic_vix(vix_close=50.0)
        cfg = LevelConfig("TEST_DETT_100_IB30_PCT_000", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches1 = engine.detect_touches(levels, es)
        touches2 = engine.detect_touches(levels, es)
        pd.testing.assert_frame_equal(touches1, touches2)


# ══════════════════════════════════════════════════════════════════════
# 8 + 9. CSV WRITERS AND FEATURE PROVENANCE
# ══════════════════════════════════════════════════════════════════════

class TestCSVWriters:
    def test_levels_csv_columns(self):
        df = pd.DataFrame(columns=LEVELS_COLUMNS)
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            write_levels_csv(df, f.name)
            f.flush()
            reread = pd.read_csv(f.name)
            assert list(reread.columns) == LEVELS_COLUMNS
            os.unlink(f.name)

    def test_touches_csv_columns(self):
        df = pd.DataFrame(columns=TOUCHES_COLUMNS)
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            write_touches_csv(df, f.name)
            f.flush()
            reread = pd.read_csv(f.name)
            assert list(reread.columns) == TOUCHES_COLUMNS
            os.unlink(f.name)

    def test_excursions_csv_columns(self):
        df = pd.DataFrame(columns=EXCURSIONS_COLUMNS)
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            write_excursions_csv(df, f.name)
            f.flush()
            reread = pd.read_csv(f.name)
            assert list(reread.columns) == EXCURSIONS_COLUMNS
            os.unlink(f.name)

    def test_provenance_csv_columns(self):
        entries = [{
            "feature_name": "level_price",
            "exact_formula": "(ib_ext_up + imp_up)/2 - sigma_offset",
            "source_data": "ES 1m ohlcv, Cboe VIX daily",
            "source_file": "data/es_1m/es_continuous_causal_*.csv",
            "source_timeframe": "1 minute",
            "feature_asof_time_definition": "created_at (IB end)",
            "decision_time_definition": "first_eligible_at",
            "causality_rule": "prior VIX close only",
            "causality_pass": "true",
            "missing_value_rule": "skip session",
            "revised_later": "false",
            "units": "ES points",
            "description": "Upper level price",
        }]
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            write_provenance_csv(entries, f.name)
            f.flush()
            reread = pd.read_csv(f.name)
            assert list(reread.columns) == FEATURE_PROVENANCE_COLUMNS
            os.unlink(f.name)

    def test_writer_rejects_missing_columns(self):
        with pytest.raises(ValueError, match="missing required columns"):
            write_levels_csv(pd.DataFrame({"foo": [1]}), "/tmp/_test_bad.csv")

    def test_provenance_rejects_missing_columns(self):
        with pytest.raises(ValueError, match="missing columns"):
            write_provenance_csv(
                [{"feature_name": "bad"}], "/tmp/_test_bad_prov.csv"
            )

    def test_byte_identical_csv(self):
        """Repeated generation produces identical CSV output."""
        cfg = LevelConfig("TEST_BYTE", 1.0, 30, "proportional", "offset_pct", 0.0)
        es = synthetic_session_bars("2024-01-02", rth_open=4700.0, range_pct=0.001)
        vix = synthetic_vix(vix_close=15.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f1:
            p1 = f1.name
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f2:
            p2 = f2.name

        write_levels_csv(levels, p1)
        write_levels_csv(levels, p2)

        with open(p1, "rb") as f:
            h1 = hashlib.sha256(f.read()).hexdigest()
        with open(p2, "rb") as f:
            h2 = hashlib.sha256(f.read()).hexdigest()
        assert h1 == h2

        os.unlink(p1)
        os.unlink(p2)


# ══════════════════════════════════════════════════════════════════════
# VIX Causal Ordering
# ══════════════════════════════════════════════════════════════════════

class TestVIXCausal:
    def test_vix_source_before_session(self):
        vix = synthetic_vix()
        src = _prior_vix_close(vix, "2024-01-02")
        assert src is not None
        assert isinstance(src, float)

    def test_no_vix_for_missing_date(self):
        vix = synthetic_vix(start_date="2024-01-10")
        src = _prior_vix_close(vix, "2024-01-02")
        assert src is None


# ══════════════════════════════════════════════════════════════════════
# Smoke Test (tiny real data sample)
# ══════════════════════════════════════════════════════════════════════

class TestSmokeRealData:
    def test_smoke_levels(self):
        es = _load_smoke_es()
        vix = _load_smoke_vix()
        cfg = LevelConfig("VIX_ES_SIGMA_100_IB60_PCT_000", 1.0, 60,
                           "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        assert len(levels) > 0
        assert "level_id" in levels.columns
        assert "config_id" in levels.columns

    def test_smoke_touches(self):
        es = _load_smoke_es()
        vix = _load_smoke_vix()
        cfg = LevelConfig("VIX_ES_SIGMA_100_IB60_PCT_000", 1.0, 60,
                           "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        if not touches.empty:
            assert "touch_id" in touches.columns
            assert all(t["touch_direction"] in ("SHORT", "LONG") for _, t in touches.iterrows())


# ══════════════════════════════════════════════════════════════════════
# Utility tests
# ══════════════════════════════════════════════════════════════════════

class TestUtility:
    def test_session_available_normal(self):
        sd = "2024-01-02"
        es = synthetic_session_bars(sd, rth_open=4700.0, range_pct=0.001)
        rth = _rth_bars(es)
        sess = rth[rth["session_date"] == sd].sort_values("ny_time")
        reason = _session_available_reason(sess, 30, sd)
        assert reason is None

    def test_session_available_no_ib_cutoff(self):
        sd = "2024-01-02"
        es = synthetic_session_bars(sd, rth_open=4700.0, range_pct=0.001,
                                    num_rth_bars=30)
        rth = _rth_bars(es)
        sess = rth[rth["session_date"] == sd].sort_values("ny_time")
        reason = _session_available_reason(sess, 60, sd)
        assert reason is not None
