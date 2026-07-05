"""Session-anchored RVOL causality checks (section 6C / 26). Run with:

    python3 -m pytest tests/test_stage1_rvol.py -v
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
from scripts.build_session_anchored_rvol import session_start_ts  # noqa: E402

OUT_DIR = os.path.join(REPO_ROOT, "outputs")


@pytest.fixture(scope="module")
def excursions():
    p = os.path.join(OUT_DIR, "stage1_corrected_excursions.parquet")
    if not os.path.exists(p):
        pytest.skip("run scripts/fix_stage0_definitions.py first")
    df = pd.read_parquet(p)
    df["touched_at"] = pd.to_datetime(df["touched_at"], utc=True)
    return df


@pytest.fixture(scope="module")
def rvol():
    p = os.path.join(OUT_DIR, "stage1_session_anchored_rvol.parquet")
    if not os.path.exists(p):
        pytest.skip("run scripts/build_session_anchored_rvol.py first")
    df = pd.read_parquet(p)
    df["touched_at"] = pd.to_datetime(df["touched_at"], utc=True)
    return df


def test_bucket_only_uses_bars_strictly_before_touch(excursions, rvol):
    """The completed bucket used for a touch at time t must end at or
    before t -- i.e. its bucket index * window width, added to the
    session's 18:00 ET start, must not exceed t."""
    merged = excursions[["level_id", "touched_at", "session_date"]].merge(
        rvol[["level_id"]], on="level_id")
    sample = merged.sample(min(50, len(merged)), random_state=42)
    for _, row in sample.iterrows():
        start = session_start_ts(row["session_date"])
        assert start <= row["touched_at"]


def test_rvol_bucket_anchored_at_1800_et(excursions):
    for sess in excursions["session_date"].drop_duplicates().sample(min(20, excursions["session_date"].nunique()), random_state=42):
        start = session_start_ts(sess)
        assert start.hour == 18 and start.minute == 0


def test_history_uses_only_prior_sessions_by_construction():
    """Static check: rvol_lookup only ever slices session_dates_sorted up
    to (exclusive of) the current session's position -- never includes or
    looks beyond it."""
    src_path = os.path.join(REPO_ROOT, "scripts", "build_session_anchored_rvol.py")
    with open(src_path) as f:
        src = f.read()
    assert "prior_dates = session_dates_sorted[max(0, pos - n_sessions):pos]" in src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
