"""Stage 1 section 6 correction invariants. Run with:

    python3 -m pytest tests/test_stage1_definitions.py -v
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
OUT_DIR = os.path.join(REPO_ROOT, "outputs")


@pytest.fixture(scope="module")
def excursions():
    p = os.path.join(OUT_DIR, "stage1_corrected_excursions.parquet")
    if not os.path.exists(p):
        pytest.skip(f"{p} not present -- run scripts/fix_stage0_definitions.py first")
    return pd.read_parquet(p)


@pytest.fixture(scope="module")
def rvol():
    p = os.path.join(OUT_DIR, "stage1_session_anchored_rvol.parquet")
    if not os.path.exists(p):
        pytest.skip(f"{p} not present -- run scripts/build_session_anchored_rvol.py first")
    return pd.read_parquet(p)


def test_original_stage0_columns_not_removed(excursions):
    for col in ("mfe", "mae", "mfe_ts", "mae_ts", "mae_before_mfe", "mfe_before_mae"):
        assert col in excursions.columns


def test_signed_fields_equal_original(excursions):
    assert (excursions["signed_mfe_pts"] == excursions["mfe"]).all()
    assert (excursions["signed_mae_pts"] == excursions["mae"]).all()


def test_conventional_mfe_mae_are_nonnegative(excursions):
    assert (excursions["conventional_mfe_pts"] >= 0).all()
    assert (excursions["conventional_mae_pts"] >= 0).all()


def test_conventional_mfe_matches_signed_floor(excursions):
    expected = excursions["signed_mfe_pts"].clip(lower=0)
    assert (excursions["conventional_mfe_pts"] == expected).all()


def test_conventional_mae_matches_negated_signed_floor(excursions):
    expected = (-excursions["signed_mae_pts"]).clip(lower=0)
    assert (excursions["conventional_mae_pts"] == expected).all()


def test_negative_signed_mfe_and_positive_signed_mae_counts(excursions):
    assert int((excursions["signed_mfe_pts"] < 0).sum()) == 72
    assert int((excursions["signed_mae_pts"] > 0).sum()) == 76


def test_rvol_session_anchored_columns_present(rvol):
    for w in (30, 60, 120):
        for n in (15, 20, 30):
            assert f"rvol_{w}m_hist{n}_session_anchored" in rvol.columns


def test_rvol_120_missing_rate_far_below_old_65_percent(rvol):
    col = "rvol_120m_hist20_session_anchored"
    missing_rate = rvol[col].isna().mean()
    assert missing_rate < 0.20, f"rvol_120m missing rate {missing_rate} did not improve enough vs the old 65%"


def test_rvol_values_within_clip_bounds(rvol):
    for c in rvol.columns:
        if c.startswith("rvol_"):
            col = rvol[c].dropna()
            if len(col):
                assert (col >= 0.10 - 1e-9).all()
                assert (col <= 10.0 + 1e-9).all()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
