"""Stage 0 evidence-lock tests for ES/VIX level discovery. Run with:

    python3 -m pytest tests/test_es_vix_stage0.py -v

Checks:
- ES continuous file properties
- VIX raw file integrity
- VIX normalized file integrity
- Holdout lock structure
- Grid definition structure and count
- Trial registry count and row validity
- Data manifest presence
"""
from __future__ import annotations

import hashlib
import json
import os
import csv

import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESEARCH_DIR = os.path.join(REPO_ROOT, "research", "es_vix_level_discovery")

# ── file paths ──────────────────────────────────────────────────────
ES_CONTINUOUS = os.path.join(REPO_ROOT, "data", "es_1m", "es_continuous_2018_2026_1m.csv")
VIX_RAW = os.path.join(REPO_ROOT, "data", "vix_raw_cboe_official.csv")
VIX_NORM = os.path.join(REPO_ROOT, "data", "vix_daily_1990_2026.csv")
HOLDOUT_JSON = os.path.join(RESEARCH_DIR, "HOLDOUT_LOCK.json")
GRID_JSON = os.path.join(RESEARCH_DIR, "GRID_DEFINITION.json")
REGISTRY_CSV = os.path.join(RESEARCH_DIR, "TRIAL_REGISTRY.csv")
MANIFEST_JSON = os.path.join(RESEARCH_DIR, "data_manifest.json")
MASTER_PLAN = os.path.join(RESEARCH_DIR, "MASTER_PLAN.md")


# ── helpers ─────────────────────────────────────────────────────────
def sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ── ES continuous ───────────────────────────────────────────────────
class TestESContinuous:
    def test_file_exists(self):
        assert os.path.exists(ES_CONTINUOUS), f"missing {ES_CONTINUOUS}"

    def test_hash(self):
        expected = "c38d850aa63172aceb03be283dc8b0f5911db73fb1ec87a250b0771d8cb078dd"
        assert sha256(ES_CONTINUOUS) == expected

    def test_record_count(self):
        df = pd.read_csv(ES_CONTINUOUS)
        assert len(df) == 2969636

    def test_coverage(self):
        df = pd.read_csv(ES_CONTINUOUS)
        ts = pd.to_datetime(df["timestamp"], utc=True)
        assert ts.iloc[0] == pd.Timestamp("2018-01-01 23:00", tz="UTC")
        assert ts.iloc[-1] == pd.Timestamp("2026-06-08 23:59", tz="UTC")

    def test_columns(self):
        df = pd.read_csv(ES_CONTINUOUS, nrows=1)
        expected = {"timestamp", "open", "high", "low", "close", "volume", "contract", "roll_day"}
        assert set(df.columns) == expected

    def test_no_duplicate_timestamps(self):
        df = pd.read_csv(ES_CONTINUOUS)
        assert df["timestamp"].is_unique, "duplicate timestamps found"

    def test_strictly_increasing_timestamps(self):
        df = pd.read_csv(ES_CONTINUOUS)
        ts = pd.to_datetime(df["timestamp"], utc=True)
        assert ts.is_monotonic_increasing


# ── VIX raw ─────────────────────────────────────────────────────────
class TestVIXRaw:
    def test_file_exists(self):
        assert os.path.exists(VIX_RAW), f"missing {VIX_RAW}"

    def test_hash(self):
        expected = "3a909bc8987edd6b6c08873a09abcc74c9697aa1b93004d6725475e21e7164b6"
        assert sha256(VIX_RAW) == expected

    def test_record_count(self):
        with open(VIX_RAW) as f:
            rows = [r for r in f.read().split("\n") if r]
        assert len(rows) == 9225  # header + 9224 data rows


# ── VIX normalized ──────────────────────────────────────────────────
class TestVIXNormalized:
    def test_file_exists(self):
        assert os.path.exists(VIX_NORM), f"missing {VIX_NORM}"

    def test_hash(self):
        expected = "af8e7d8e1d139ed258f2a117df54c76464277866cd5466cd256e89ac629746a1"
        assert sha256(VIX_NORM) == expected

    def test_record_count(self):
        df = pd.read_csv(VIX_NORM)
        assert len(df) == 9224, f"expected 9224 rows, got {len(df)}"

    def test_columns(self):
        df = pd.read_csv(VIX_NORM, nrows=1)
        expected = {"date", "vix_open", "vix_high", "vix_low", "vix_close"}
        assert set(df.columns) == expected

    def test_vix_range(self):
        df = pd.read_csv(VIX_NORM)
        assert df["vix_close"].min() > 0
        assert df["vix_close"].max() < 100

    def test_no_nulls(self):
        df = pd.read_csv(VIX_NORM)
        assert df.isnull().sum().sum() == 0, "null values found"


# ── Holdout lock ────────────────────────────────────────────────────
class TestHoldoutLock:
    def test_file_exists(self):
        assert os.path.exists(HOLDOUT_JSON)

    def test_structure(self):
        with open(HOLDOUT_JSON) as f:
            lock = json.load(f)
        assert lock["strategy"] == "es_vix_level_discovery"
        assert lock["holdout_start"] == "2025-01-01"
        assert lock["holdout_end"] == "2026-06-08"
        assert lock["development_start"] == "2018-01-01"
        assert lock["development_end"] == "2024-12-31"


# ── Grid definition ─────────────────────────────────────────────────
class TestGridDefinition:
    def test_file_exists(self):
        assert os.path.exists(GRID_JSON)

    def test_total_configs(self):
        with open(GRID_JSON) as f:
            grid = json.load(f)
        assert grid["total_configurations"] == 132

    def test_parameter_space_product(self):
        with open(GRID_JSON) as f:
            grid = json.load(f)
        ps = grid["parameter_space"]
        product = len(ps["sigma_multiplier"]) * len(ps["fixed_offset"]) * len(ps["line_life_sessions"])
        assert product == 132, f"parameter space product = {product}, expected 132"


# ── Trial registry ──────────────────────────────────────────────────
class TestTrialRegistry:
    def test_file_exists(self):
        assert os.path.exists(REGISTRY_CSV)

    def test_row_count(self):
        with open(REGISTRY_CSV) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 132, f"expected 132 rows, got {len(rows)}"

    def test_all_registered(self):
        with open(REGISTRY_CSV) as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            assert r["status"] == "registered", f"{r['trial_id']} status = {r['status']}"

    def test_unique_combos(self):
        with open(REGISTRY_CSV) as f:
            rows = list(csv.DictReader(f))
        combos = {(r["sigma_multiplier"], r["fixed_offset"], r["line_life_sessions"]) for r in rows}
        assert len(combos) == 132, f"expected 132 unique combos, got {len(combos)}"


# ── Data manifest ───────────────────────────────────────────────────
class TestDataManifest:
    def test_file_exists(self):
        assert os.path.exists(MANIFEST_JSON), f"missing {MANIFEST_JSON}"

    def test_hashes_match(self):
        with open(MANIFEST_JSON) as f:
            mf = json.load(f)
        files = mf["files"]
        assert sha256(ES_CONTINUOUS) == files["es_continuous"]["sha256"]
        assert sha256(VIX_RAW) == files["vix_raw_cboe"]["sha256"]
        assert sha256(VIX_NORM) == files["vix_normalized"]["sha256"]


# ── Master plan ─────────────────────────────────────────────────────
class TestMasterPlan:
    def test_file_exists(self):
        assert os.path.exists(MASTER_PLAN)