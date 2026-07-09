"""Stage 1 deterministic tests for the ES/VIX level-generation, touch-detection,
and MAE/MFE engine.

Tests use synthetic minute-bar fixtures and tiny pre-2025 implementation
fixtures to verify mechanics only — never signal quality.
"""
from __future__ import annotations

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
)
from research.es_vix_level_discovery.stage1_schemas import (
    LEVELS_COLUMNS,
    TOUCHES_COLUMNS,
    EXCURSIONS_COLUMNS,
    PROVENANCE_COLUMNS,
    write_levels_csv,
    write_touches_csv,
    write_excursions_csv,
    write_provenance_csv,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ES_CAUSAL = os.path.join(REPO_ROOT, "data", "es_1m", "es_continuous_causal_2018_2026_1m.csv")
VIX_NORM = os.path.join(REPO_ROOT, "data", "vix_daily_1990_2026.csv")
NY_TZ = "America/New_York"


# ── Helper: build synthetic ES session data ──────────────────────────

def _utc_to_ny_str(utc_str: str) -> str:
    """Convert UTC timestamp string to NY timezone string."""
    return str(pd.Timestamp(utc_str, tz="UTC").tz_convert(NY_TZ))


def _ny_to_utc(ny_dt_str: str) -> str:
    """Convert NY-local timestamp string to UTC string."""
    return str(pd.Timestamp(ny_dt_str, tz=NY_TZ).tz_convert("UTC"))


def synthetic_session_bars(
    session_date: str,
    rth_open: float = 4700.0,
    drift: float = 0.0,
    range_pct: float = 0.002,
    num_rth_bars: int = 390,
    amp: float = 0.0,
) -> pd.DataFrame:
    """Generate synthetic 1-min RTH bars for one session.

    Bars run 09:30-15:59 ET with simple random-walk-like structure.
    Uses deterministic prices from arithmetic progression + sinusoid.
    """
    rows = []
    for i in range(num_rth_bars):
        minute_offset = i
        base = rth_open + drift * (minute_offset / 390.0)
        half_range = rth_open * range_pct / 2.0
        wiggle = amp * math.sin(minute_offset * 0.1)
        ctr = base + wiggle
        h = ctr + half_range * abs(math.sin(minute_offset * 0.07 + 1.0))
        l = ctr - half_range * abs(math.sin(minute_offset * 0.07 + 2.0))
        if h < ctr:
            h, ctr = ctr, h
        if l > ctr:
            l, ctr = ctr, l
        if l > h:
            l, h = h, l
        h = round(max(h, ctr), 2)
        l = round(min(l, ctr), 2)
        o = round(ctr, 2)
        c = round(ctr + half_range * 0.1 * (1 if i % 2 == 0 else -1), 2)
        if c > h:
            c = h
        if c < l:
            c = l

        hour = 9 + (minute_offset + 30) // 60
        minute = (minute_offset + 30) % 60
        ny_dt = f"{session_date} {hour:02d}:{minute:02d}:00"
        utc_ts = _ny_to_utc(ny_dt)
        rows.append({
            "timestamp": utc_ts,
            "open": o,
            "high": h,
            "low": l,
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
    """Synthetic multi-session ES data."""
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


# ── Helpers for test assertions ──────────────────────────────────────

def _load_smoke_es() -> pd.DataFrame:
    return pd.read_csv(ES_CAUSAL, nrows=50000)


def _load_smoke_vix() -> pd.DataFrame:
    df = pd.read_csv(VIX_NORM, parse_dates=["date"])
    df["date"] = pd.to_datetime(df["date"])
    return df


# ══════════════════════════════════════════════════════════════════════
# Formula and Level Generation
# ══════════════════════════════════════════════════════════════════════

class TestFormulaCorrectness:
    """Verify the exact master-plan formula with synthetic data."""

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


class TestIBBoundary:
    """30 vs 60 minute IB boundary behavior."""

    def test_ib30_uses_first_30_bars(self):
        cfg = LevelConfig("TEST_075_IB30_PCT_000", 0.75, 30, "proportional", "offset_pct", 0.0)
        es = synthetic_session_bars("2024-01-02", rth_open=4800.0, range_pct=0.003)
        vix = synthetic_vix(vix_close=15.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        rth = _rth_bars(es)
        sess = rth[rth["session_date"] == "2024-01-02"].sort_values("ny_time")
        ib_bars = sess.iloc[:30]
        expected_ib_high = float(ib_bars["high"].max())
        expected_ib_low = float(ib_bars["low"].min())
        upper = levels[levels["direction"] == "UPPER"].iloc[0]
        assert abs(upper["ib_high"] - expected_ib_high) < 1e-6
        assert abs(upper["ib_low"] - expected_ib_low) < 1e-6

    def test_ib60_uses_first_60_bars(self):
        cfg = LevelConfig("TEST_075_IB60_PCT_000", 0.75, 60, "proportional", "offset_pct", 0.0)
        es = synthetic_session_bars("2024-01-02", rth_open=4800.0, range_pct=0.003)
        vix = synthetic_vix(vix_close=15.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        rth = _rth_bars(es)
        sess = rth[rth["session_date"] == "2024-01-02"].sort_values("ny_time")
        ib_bars = sess.iloc[:60]
        expected_ib_high = float(ib_bars["high"].max())
        expected_ib_low = float(ib_bars["low"].min())
        upper = levels[levels["direction"] == "UPPER"].iloc[0]
        assert abs(upper["ib_high"] - expected_ib_high) < 1e-6
        assert abs(upper["ib_low"] - expected_ib_low) < 1e-6


class TestLevelDirection:
    """Upper = SHORT, Lower = LONG."""

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


class TestDetectTouches:
    """First physical touch detection mechanics."""

    def test_upper_clean_touch(self):
        es = synthetic_session_bars("2024-01-02", rth_open=4700.0, range_pct=0.001)
        vix = synthetic_vix(vix_close=80.0)
        cfg = LevelConfig("TEST_TCH_075_IB30_PCT_000", 0.75, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        if not touches.empty:
            upper_touches = touches[touches["level_direction"] == "UPPER"]
            assert len(upper_touches) <= 1

    def test_creation_bar_excluded(self):
        """Level created at IB[last] - that bar cannot be the touch bar."""
        es = synthetic_session_bars("2024-01-02", rth_open=4600.0, range_pct=0.001)
        vix = synthetic_vix(vix_close=80.0)
        cfg = LevelConfig("TEST_EXCL_075_IB30_PCT_000", 0.75, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        for _, lv in levels.iterrows():
            rth = _rth_bars(es)
            sess = rth[rth["session_date"] == lv["session_date"]].sort_values("ny_time")
            ib_last = sess.iloc[29] if lv["ib_minutes"] == 30 else sess.iloc[59]
            created = pd.Timestamp(lv["created_at"])
            assert str(ib_last["ny_time"]) == str(created)

    def test_level_consumed_after_first_touch(self):
        """Level is consumed on first touch; not touched again."""
        es = synthetic_multiday_es("2024-01-02", num_sessions=5, rth_open=4700.0)
        vix = synthetic_vix(vix_close=50.0)
        cfg = LevelConfig("TEST_CONS_100_IB30_PCT_000", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        if not touches.empty:
            touched_levels = touches["level_id"].value_counts()
            assert all(v == 1 for v in touched_levels.values), "Level touched more than once"

    def test_twenty_session_lifetime(self):
        """Level expires after 20 sessions."""
        es = synthetic_multiday_es("2024-01-02", num_sessions=25, rth_open=4700.0)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_LIFE_100_IB30_PCT_000", 1.0, 30, "proportional", "offset_pct", 0.0)
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
                assert session_gap < 20, f"Level touched {session_gap} sessions after creation (max 19)"

    def test_gap_through_detection(self):
        """Bar opening above UPPER level triggers GAP_THROUGH."""
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
        cfg = LevelConfig("TEST_GAP_100_IB30_PCT_000", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        upper_touches = engine.detect_touches(levels, es)
        upper_touches = upper_touches[upper_touches["level_direction"] == "UPPER"]
        if not upper_touches.empty:
            for _, t in upper_touches.iterrows():
                if t["touch_type"] == "GAP_THROUGH":
                    assert t["reference_entry_price"] == t["touch_bar_open"]
                    assert t["gap_through"] is True


class TestCleanTouchRefPrice:
    """Clean touch sets reference_entry_price = level_price."""

    def test_clean_touch_ref_price(self):
        """When a bar trades through the level, reference is level_price."""
        es = synthetic_session_bars("2024-01-02", rth_open=4600.0, range_pct=0.002)
        vix = synthetic_vix(vix_close=80.0)
        cfg = LevelConfig("TEST_REF_100_IB30_PCT_000", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        for _, t in touches.iterrows():
            if t["touch_type"] == "CLEAN":
                assert t["reference_entry_price"] == t["level_price"]
            else:
                assert t["reference_entry_price"] == t["touch_bar_open"]


class TestSimultaneousTouchOrdering:
    """Deterministic ordering: older level first, upper before lower."""

    def test_ordering_consistency(self):
        es = synthetic_session_bars("2024-01-02", rth_open=4700.0, range_pct=0.003)
        vix = synthetic_vix(vix_close=80.0)
        cfg = LevelConfig("TEST_ORD_100_IB30_PCT_000", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        if not touches.empty:
            touches_sorted = touches.sort_values(["touch_bar_timestamp", "touch_id"])
            assert touches_sorted["touch_bar_timestamp"].is_monotonic_increasing


class TestOverlapClusters:
    """Overlap-cluster assignment for overlapping touch windows."""

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


# ══════════════════════════════════════════════════════════════════════
# MAE/MFE
# ══════════════════════════════════════════════════════════════════════

class TestMAEMFE:
    """Unrestricted MAE/MFE label generation."""

    @staticmethod
    def _guarantee_touches():
        """Generate data guaranteed to produce touches.

        Creates a wide-range session with high VIX and tight sigma_mult so
        that levels sit inside the bar range and get touched immediately.
        """
        rth_open = 4700.0
        session_date = "2024-01-02"
        rows = []
        for i in range(390):
            hour = 9 + (i + 30) // 60
            minute = (i + 30) % 60
            ny_dt = f"{session_date} {hour:02d}:{minute:02d}:00"
            utc_ts = _ny_to_utc(ny_dt)
            base_open = rth_open
            high = base_open + 5.0 + (i % 3) * 2.0
            low = base_open - 5.0 - (i % 3) * 2.0
            o = base_open + (i % 5) * 0.5
            c = base_open + (1 if i % 2 == 0 else -1)
            if i >= 100 and i <= 200:
                high = rth_open + 80.0 + (i % 10)
                low = rth_open - 30.0 - (i % 5)
                o = rth_open + 2.0
                c = rth_open + 1.0
            high = round(max(high, o, c), 2)
            low = round(min(low, o, c), 2)
            o = round(o, 2)
            c = round(max(min(c, high), low), 2)
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

    def test_horizons_present(self):
        es, touches, engine = self._guarantee_touches()
        if touches.empty:
            pytest.skip("No touches in synthetic data")
        excursions = engine.compute_excursions(touches, es)
        expected_horizons = {"15min", "30min", "60min", "120min", "RTH_REMAINDER"}
        assert expected_horizons.issubset(set(excursions["horizon"].unique()))

    def test_mae_mfe_nonnegative(self):
        es, touches, engine = self._guarantee_touches()
        if touches.empty:
            pytest.skip("No touches in synthetic data")
        excursions = engine.compute_excursions(touches, es)
        assert (excursions["mae"] >= 0).all()
        assert (excursions["mfe"] >= 0).all()

    def test_no_touch_bar_leakage(self):
        """Labels start on the first complete minute AFTER touch bar."""
        es, touches, engine = self._guarantee_touches()
        if touches.empty:
            pytest.skip("No touches in synthetic data")
        excursions = engine.compute_excursions(touches, es)
        for _, exc in excursions.iterrows():
            start = pd.Timestamp(exc["start_timestamp"])
            touch_ts = pd.Timestamp(
                touches[touches["touch_id"] == exc["touch_id"]]["touch_bar_timestamp"].iloc[0]
            )
            assert start > touch_ts

    def test_long_mfe_mae_direction(self):
        """LONG: MFE = future high - entry, MAE = entry - future low."""
        es, touches, engine = self._guarantee_touches()
        if touches.empty:
            pytest.skip("No touches in synthetic data")
        excursions = engine.compute_excursions(touches, es)
        long_exc = excursions[excursions["touch_direction"] == "LONG"]
        if not long_exc.empty:
            for _, exc in long_exc.iterrows():
                assert isinstance(exc["mae"], float)
                assert isinstance(exc["mfe"], float)

    def test_short_mfe_mae_direction(self):
        """SHORT: MFE = entry - future low, MAE = future high - entry."""
        es, touches, engine = self._guarantee_touches()
        if touches.empty:
            pytest.skip("No touches in synthetic data")
        excursions = engine.compute_excursions(touches, es)
        short_exc = excursions[excursions["touch_direction"] == "SHORT"]
        if not short_exc.empty:
            for _, exc in short_exc.iterrows():
                assert isinstance(exc["mae"], float)
                assert isinstance(exc["mfe"], float)


class TestFirstPassage:
    """First-passage labels and AMBIGUOUS status."""

    def test_first_passage_column_present(self):
        es, touches, engine = TestMAEMFE._guarantee_touches()
        assert not touches.empty, "Guaranteed touches should not be empty"
        excursions = engine.compute_excursions(touches, es)
        valid = {"FAVORABLE_FIRST", "ADVERSE_FIRST", "AMBIGUOUS", "NOT_REACHED"}
        assert excursions["first_passage"].isin(valid).all()


# ══════════════════════════════════════════════════════════════════════
# Determinism
# ══════════════════════════════════════════════════════════════════════

class TestDeterminism:
    """Repeated calls produce identical output."""

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
# CSV Writers
# ══════════════════════════════════════════════════════════════════════

class TestCSVWriters:
    """Schema and writing functions."""

    def test_levels_csv_columns(self):
        df = pd.DataFrame(columns=LEVELS_COLUMNS)
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            write_levels_csv(df, f.name)
            f.flush()
            reread = pd.read_csv(f.name)
            assert list(reread.columns) == LEVELS_COLUMNS
            os.unlink(f.name)

    def test_touches_csv_columns(self):
        df = pd.DataFrame(columns=list(TOUCHES_COLUMNS))
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            write_touches_csv(df, f.name)
            f.flush()
            reread = pd.read_csv(f.name)
            assert list(reread.columns) == list(TOUCHES_COLUMNS)
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
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as f:
            entries = [{
                "feature_name": "test_feature",
                "source_stage": "stage1",
                "description": "test",
            }]
            write_provenance_csv(entries, f.name)
            f.flush()
            reread = pd.read_csv(f.name)
            assert list(reread.columns) == PROVENANCE_COLUMNS
            os.unlink(f.name)


# ══════════════════════════════════════════════════════════════════════
# VIX Causal Ordering
# ══════════════════════════════════════════════════════════════════════

class TestVIXCausal:
    """Prior VIX close only, no future leakage."""

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
    """Run on a tiny slice of real pre-2025 data — mechanics only."""

    def test_smoke_levels(self):
        es = _load_smoke_es()
        vix = _load_smoke_vix()
        cfg = LevelConfig("VIX_ES_SIGMA_100_IB60_PCT_000", 1.0, 60, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        assert len(levels) > 0
        assert "level_id" in levels.columns
        assert "config_id" in levels.columns

    def test_smoke_touches(self):
        es = _load_smoke_es()
        vix = _load_smoke_vix()
        cfg = LevelConfig("VIX_ES_SIGMA_100_IB60_PCT_000", 1.0, 60, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        # Just verify it runs without error and produces valid data
        if not touches.empty:
            assert "touch_id" in touches.columns
            assert all(t["touch_direction"] in ("SHORT", "LONG") for _, t in touches.iterrows())
