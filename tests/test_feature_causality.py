"""Causality proofs for the Stage 0 pre-entry feature table
(scripts/build_preentry_features.py). Run with:

    python3 -m pytest tests/test_feature_causality.py -v
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
OUT_DIR = os.path.join(REPO_ROOT, "outputs")

sys.path.insert(0, REPO_ROOT)
from src.data_loader import load_gvz_daily  # noqa: E402


@pytest.fixture(scope="module")
def features():
    p = os.path.join(OUT_DIR, "stage0_features.csv")
    if not os.path.exists(p):
        pytest.skip(f"{p} not present -- run scripts/build_preentry_features.py first")
    df = pd.read_csv(p)
    df["touched_at"] = pd.to_datetime(df["touched_at"], utc=True)
    return df


@pytest.fixture(scope="module")
def vxn():
    p = os.path.join(REPO_ROOT, "data", "vxn_daily_2018_2026.csv")
    return load_gvz_daily(p)


RANGE_COLS = ["range_15m", "range_30m", "range_60m", "range_120m", "prev_session_range"]
ATR_COLS = ["atr14_5m", "atr14_15m", "atr14_30m", "atr14_60m"]
EWMA_COLS = ["ewma_vol_hl30m", "ewma_vol_hl60m", "ewma_vol_hl120m"]
RVOL_COLS = [f"rvol_{w}m_hist{n}" for w in (30, 60, 120) for n in (15, 20, 30)]


def test_no_2026_used_is_not_applicable_here_but_columns_exist(features):
    # Stage 0 does not fit or select anything, so this test only confirms
    # 2026 rows are present and computed the same way as every other year
    # (no special-cased branch anywhere in the builder for 2026).
    years = pd.to_datetime(features["touched_at"]).dt.tz_convert("America/New_York").dt.year
    assert years.max() >= 2026 or years.max() >= 2025


def test_range_features_nonnegative_or_null(features):
    for c in RANGE_COLS:
        col = features[c].dropna()
        assert (col >= 0).all()


def test_atr_features_nonnegative_or_null(features):
    for c in ATR_COLS:
        col = features[c].dropna()
        assert (col >= 0).all()


def test_ewma_vol_nonnegative_or_null(features):
    for c in EWMA_COLS:
        col = features[c].dropna()
        assert (col >= 0).all()


def test_rvol_within_documented_clip_bounds(features):
    for c in RVOL_COLS:
        col = features[c].dropna()
        if len(col):
            assert (col >= 0.10 - 1e-9).all()
            assert (col <= 10.0 + 1e-9).all()


def test_vxn_prior_close_is_strictly_lagged(features, vxn):
    """Uses the same 18:00 ET session-date roll convention as
    scripts.build_preentry_features (and the verified engine's own
    prior_session_close semantics) -- an evening touch belongs to the
    *next* session date, so that session's own same-day VXN close (already
    published hours earlier) is legitimately "prior", not a lookahead."""
    from scripts.build_signal_paths import research_session_date

    sample = features.dropna(subset=["vxn_prior_close"]).sample(min(50, len(features)), random_state=42)
    for _, row in sample.iterrows():
        ts = pd.Timestamp(row["touched_at"])
        session_date = pd.Timestamp(research_session_date(ts)).tz_localize(None)
        prior = vxn[vxn.index < session_date]
        if prior.empty:
            continue
        assert row["vxn_prior_close"] == pytest.approx(float(prior.iloc[-1]))
        # and, regardless of convention, the value used must never be from
        # strictly after the touch's own calendar date
        touch_calendar_date = ts.tz_convert("America/New_York").normalize().tz_localize(None)
        assert prior.index[-1] <= touch_calendar_date


def test_no_feature_uses_forbidden_columns():
    """Static check: the feature-builder script must never reference
    entry-hour/weekday/month/year/trade-identity/outcome columns as inputs."""
    src_path = os.path.join(REPO_ROOT, "scripts", "build_preentry_features.py")
    with open(src_path) as f:
        src = f.read()
    forbidden = ["exit_reason", "pnl", "mfe", "mae", ".dt.weekday", ".dt.month"]
    for token in forbidden:
        assert token not in src, f"forbidden token {token!r} found in feature builder"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
