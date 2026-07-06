"""Structural / fail-closed unit tests for
scripts/og_external_2013_2015_dual_config.py. Mirrors the pattern used for
the locked-validation runner's tests where present: these tests check
argument validation and fail-closed behavior only -- they do not assert any
strategy-outcome number (the actual run happens exactly once, separately)."""
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from scripts.og_external_2013_2015_dual_config import (
    ExternalDiagFailClosed, main, EXTERNAL_YEARS, WARMUP_ONLY_YEARS,
)

CFG_PRIMARY = os.path.join(REPO_ROOT, "configs/OG_PRIMARY_150R.yaml")
CFG_OPERATIONAL = os.path.join(REPO_ROOT, "configs/OG_OPERATIONAL_100R.yaml")
BARS = "data/external_2013_2015/normalized/nq_continuous_2013_2015_1m.csv"
VXN = "data/external_2013_2015/normalized/vxn_daily_2012warmup_2015.csv"
OUT = os.path.join(REPO_ROOT, "outputs/og_external_2013_2015/_test_tmp")


def test_years_must_be_exact_external_set():
    with pytest.raises(ExternalDiagFailClosed, match="--years must be exactly"):
        main([
            "--years", "2013", "2014",
            "--config", CFG_PRIMARY, "--config", CFG_OPERATIONAL,
            "--bars", BARS, "--vxn", VXN, "--out-dir", OUT,
        ])


def test_build_years_rejected():
    with pytest.raises(ExternalDiagFailClosed, match="--years must be exactly"):
        main([
            "--years", "2018", "2020", "2023",
            "--config", CFG_PRIMARY, "--config", CFG_OPERATIONAL,
            "--bars", BARS, "--vxn", VXN, "--out-dir", OUT,
        ])


def test_2016_2017_rejected():
    with pytest.raises(ExternalDiagFailClosed, match="--years must be exactly"):
        main([
            "--years", "2013", "2014", "2015", "2016",
            "--config", CFG_PRIMARY, "--config", CFG_OPERATIONAL,
            "--bars", BARS, "--vxn", VXN, "--out-dir", OUT,
        ])


def test_requires_exactly_two_configs():
    with pytest.raises(ExternalDiagFailClosed, match="exactly two --config"):
        main([
            "--years", "2013", "2014", "2015",
            "--config", CFG_PRIMARY,
            "--bars", BARS, "--vxn", VXN, "--out-dir", OUT,
        ])


def test_missing_bars_file_fails_closed():
    with pytest.raises(ExternalDiagFailClosed, match="--bars file not found"):
        main([
            "--years", "2013", "2014", "2015",
            "--config", CFG_PRIMARY, "--config", CFG_OPERATIONAL,
            "--bars", "data/does_not_exist.csv", "--vxn", VXN, "--out-dir", OUT,
        ])


def test_bars_hash_mismatch_fails_closed(tmp_path):
    bad_bars = tmp_path / "bad_bars.csv"
    bad_bars.write_text("timestamp,open,high,low,close,volume\n2013-01-02 11:00:00+00:00,1,1,1,1,1\n")
    with pytest.raises(ExternalDiagFailClosed, match="sha256"):
        main([
            "--years", "2013", "2014", "2015",
            "--config", CFG_PRIMARY, "--config", CFG_OPERATIONAL,
            "--bars", str(bad_bars), "--vxn", VXN, "--out-dir", OUT,
        ])


def test_external_years_constant_excludes_warmup_year():
    assert 2012 not in EXTERNAL_YEARS
    assert WARMUP_ONLY_YEARS == frozenset({2012})
    assert EXTERNAL_YEARS == frozenset({2013, 2014, 2015})
