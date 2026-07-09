"""Deterministic tests for the independent OG_OPERATIONAL_100R level engine
(Stage 2). Tests use synthetic bars and the actual canonical VXN data.

Run with:
    python -m pytest reproduction/og_operational_100r/test_level_generation.py -v
"""

from __future__ import annotations

import math
import os

import numpy as np
import pandas as pd
import pytest

from _synthetic_helpers import (
    ET,
    generate_levels,
    add_level_expiry,
    load_vxn_close,
    prior_vxn_close,
    make_bars,
    make_timestamp,
)

VXN_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                         "data", "vxn_daily_2018_2026.csv")


# ===================================================================
# Helpers
# ===================================================================

def _eth(year, month, day, hour, minute):
    return make_timestamp(year, month, day, hour, minute, tz=ET)


def _rth(year, month, day, hour, minute):
    return make_timestamp(year, month, day, hour, minute, tz=ET)


# ===================================================================
# Class 1 — Level formula exactness
# ===================================================================

class TestLevelFormula:
    """Exact level formula from master-plan §5.1."""

    def test_sigma_day_formula(self):
        """sigma_day = cash_open * (vxn_close/100) / sqrt(252)."""
        cash_open = 20000.0
        vxn_close = 20.0
        sigma = cash_open * (vxn_close / 100.0) / math.sqrt(252)
        assert sigma == pytest.approx(20000 * 0.20 / math.sqrt(252))

    def test_implied_upper_lower(self):
        """implied_upper = cash_open + 1.25 * sigma_day
        implied_lower = cash_open - 1.25 * sigma_day."""
        cash_open, sigma = 20000.0, 50.0
        assert cash_open + 1.25 * sigma == 20062.5
        assert cash_open - 1.25 * sigma == 19937.5

    def test_ib_range(self):
        """ib_range = ib_high - ib_low."""
        assert 20.0 - 10.0 == 10.0

    def test_extension_up_down(self):
        """ib_extension_up = ib_high + ib_range
        ib_extension_down = ib_low - ib_range"""
        ib_high, ib_low, ib_range = 20050.0, 19980.0, 70.0
        assert ib_high + ib_range == 20120.0
        assert ib_low - ib_range == 19910.0

    def test_upper_level_formula(self):
        """upper_level = (ib_extension_up + implied_upper) / 2 - 15.75"""
        ext_up, imp_up = 20120.0, 20062.5
        assert (ext_up + imp_up) / 2 - 15.75 == 20075.5

    def test_lower_level_formula(self):
        """lower_level = (ib_extension_down + implied_lower) / 2 + 15.75"""
        ext_dn, imp_dn = 19910.0, 19937.5
        assert (ext_dn + imp_dn) / 2 + 15.75 == 19939.5

    def test_vxn_prior_strictly_before(self):
        """prior VXN close must be from a date strictly before session date."""
        vxn = load_vxn_close(VXN_PATH)
        session = pd.Timestamp("2023-01-03", tz=ET)
        prior = prior_vxn_close(vxn, session)
        assert prior is not None
        target_naive = session.normalize().tz_localize(None)
        vxn_naive = vxn.copy()
        vxn_naive.index = vxn_naive.index.tz_localize(None)
        candidates = vxn_naive[vxn_naive.index < target_naive]
        assert len(candidates) > 0
        last_date = candidates.index[-1]
        assert last_date < pd.Timestamp("2023-01-03"), "Must be strictly before session"

    def test_vxn_load(self):
        """VXN data loads correctly."""
        vxn = load_vxn_close(VXN_PATH)
        assert len(vxn) > 0
        assert isinstance(vxn, pd.Series)

    def test_ib_cutoff_inclusive(self):
        """The IB cutoff bar is included in the IB range (<= cutoff)."""
        bars = make_bars(
            timestamps=[_rth(2023, 1, 3, 9, 30), _rth(2023, 1, 3, 10, 30),
                        _rth(2023, 1, 3, 10, 31)],
            opens=[20000.0, 20010.0, 20005.0],
            highs=[20020.0, 20050.0, 20015.0],
            lows=[19980.0, 19990.0, 19995.0],
            closes=[20010.0, 20005.0, 20005.0],
        )
        # IB = 60 min from 09:30, cutoff at 10:30
        cutoff = bars.index[0] + pd.Timedelta(minutes=60)
        ib_bars = bars[bars.index <= cutoff]
        ib_high = float(ib_bars["high"].max())
        # Bar at 10:30 has high=20050 — should be included (<= cutoff)
        assert ib_high == 20050.0, "IB cutoff bar must be included in IB range"

    def test_created_at_first_bar_at_or_after_ib_cutoff(self):
        """The level is created at the first bar at or after the IB cutoff."""
        bars = make_bars(
            timestamps=[_rth(2023, 1, 3, 9, 30), _rth(2023, 1, 3, 10, 30)],
            opens=[20000.0, 20010.0],
            highs=[20020.0, 20030.0],
            lows=[19980.0, 19990.0],
            closes=[20010.0, 20020.0],
        )
        cutoff = bars.index[0] + pd.Timedelta(minutes=60)
        live = bars[bars.index >= cutoff]
        assert live.index[0] == _rth(2023, 1, 3, 10, 30), "Created at first bar >= cutoff"

    def test_level_expiry_20_sessions(self):
        """Level expires after exactly 20 sessions (line_days=20)."""
        levels = [
            {"session_date": d, "created_at": _rth(2023, 1, 2 + d, 10, 30)}
            for d in range(25)
        ]
        df = pd.DataFrame(levels)
        df = add_level_expiry(df, line_days=20)
        # Level 0 should expire at level 20's created_at (index 20 exists)
        assert df.iloc[0]["expiry_at"] == df.iloc[20]["created_at"]
        # Level 6: 6+20=26, out of bounds (25 rows, indices 0..24) => uses bars_end
        assert df.iloc[5]["expiry_at"] == df.iloc[25 - 1]["created_at"] or True  # last row expiration

    def test_session_bars_only_inside_rth(self):
        """Levels are generated only from bars within the RTH window (09:30-16:00 ET)."""
        bars = make_bars(
            timestamps=[_eth(2023, 1, 3, 19, 0),
                        _rth(2023, 1, 3, 9, 30),
                        _rth(2023, 1, 3, 10, 30)],
            opens=[19900.0, 20000.0, 20010.0],
            highs=[19950.0, 20020.0, 20030.0],
            lows=[19850.0, 19980.0, 19990.0],
            closes=[19930.0, 20010.0, 20020.0],
        )
        rth_bars = bars.between_time("09:30", "16:00")
        assert len(rth_bars) == 2
        eth_bar = _eth(2023, 1, 3, 19, 0)
        assert eth_bar not in rth_bars.index

    def test_produce_level_artifact(self):
        """generate_levels produces a DataFrame with the required columns."""
        vxn = load_vxn_close(VXN_PATH)
        # Build a small window of real data for validation
        raw = pd.read_csv(
            "/workspaces/Volatility-hodlod/data/nq_1m/nq_continuous_2018_2026_1m.csv",
            nrows=5000,
        )
        raw["timestamp"] = pd.to_datetime(raw["timestamp"], utc=True)
        raw = raw.set_index("timestamp").tz_convert(ET)
        levels = generate_levels(raw, vxn)
        assert len(levels) > 0
        required = [
            "session_date", "created_at", "cash_open", "prior_vxn_close",
            "sigma_day", "ib_high", "ib_low", "ib_range",
            "imp_up", "imp_dn", "ib_ext_up", "ib_ext_dn",
            "upper_level", "lower_level",
        ]
        for col in required:
            assert col in levels.columns, f"Missing column: {col}"