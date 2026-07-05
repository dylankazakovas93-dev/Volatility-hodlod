"""Data-layer checks for the canonical NQ bars + VXN daily files. Run with:

    python3 -m pytest tests/test_data.py -v

Requires the two files to exist locally per data/README.md.
"""
from __future__ import annotations

import hashlib
import os
import sys

import pandas as pd
import pytest
import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.data_loader import load_1m_ohlcv  # noqa: E402

CONFIG_PATH = os.path.join(REPO_ROOT, "configs", "nq_current_config.yaml")


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def bars_path(config):
    p = os.path.join(REPO_ROOT, config["data"]["bars_file"])
    if not os.path.exists(p):
        pytest.skip(f"{p} not present locally -- see data/README.md")
    return p


@pytest.fixture(scope="module")
def vxn_path(config):
    p = os.path.join(REPO_ROOT, config["data"]["vxn_file"])
    if not os.path.exists(p):
        pytest.skip(f"{p} not present locally -- see data/README.md")
    return p


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def test_canonical_row_count(bars_path, config):
    with open(bars_path) as f:
        n = sum(1 for _ in f) - 1
    assert n == config["data"]["bars_rows"] == 2964655


def test_canonical_bars_hash(bars_path, config):
    assert sha256_file(bars_path) == config["data"]["bars_sha256"]


def test_canonical_vxn_hash(vxn_path, config):
    assert sha256_file(vxn_path) == config["data"]["vxn_sha256"]


def test_bars_have_required_ohlc_fields(bars_path):
    df = pd.read_csv(bars_path, nrows=1000)
    cols = {c.lower() for c in df.columns}
    for required in ("open", "high", "low", "close"):
        assert required in cols


def test_bars_chronological_order(bars_path):
    bars = load_1m_ohlcv(bars_path)
    assert bars.index.is_monotonic_increasing


def test_bars_no_duplicate_timestamps(bars_path):
    bars = load_1m_ohlcv(bars_path)
    dupes = bars.index[bars.index.duplicated()]
    assert len(dupes) == 0, f"unexplained duplicate timestamps: {len(dupes)}"


def test_bars_valid_ohlc_relationships(bars_path):
    bars = load_1m_ohlcv(bars_path)
    assert (bars["high"] >= bars["low"]).all()
    assert (bars["high"] >= bars["open"]).all()
    assert (bars["high"] >= bars["close"]).all()
    assert (bars["low"] <= bars["open"]).all()
    assert (bars["low"] <= bars["close"]).all()


def test_bars_timezone_is_america_new_york(bars_path):
    bars = load_1m_ohlcv(bars_path)
    assert str(bars.index.tz) == "America/New_York"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
