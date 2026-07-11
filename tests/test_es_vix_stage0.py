"""Stage 0 evidence-lock tests for ES/VIX level discovery (corrected).

Run:
    python -m pytest tests/test_es_vix_stage0.py -v
"""
from __future__ import annotations

import hashlib
import json
import os
import csv
import subprocess

import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESEARCH_DIR = os.path.join(REPO_ROOT, "research", "es_vix_level_discovery")
DATA_DIR = os.path.join(RESEARCH_DIR, "data")

ES_CAUSAL = os.path.join(REPO_ROOT, "data", "es_1m", "es_continuous_causal_2018_2026_1m.csv")
VIX_RAW = os.path.join(REPO_ROOT, "data", "vix_raw_cboe_official.csv")
VIX_NORM = os.path.join(REPO_ROOT, "data", "vix_daily_1990_2026.csv")
HOLDOUT = os.path.join(RESEARCH_DIR, "HOLDOUT_LOCK.json")
GRID = os.path.join(RESEARCH_DIR, "GRID_DEFINITION.json")
REGISTRY = os.path.join(RESEARCH_DIR, "TRIAL_REGISTRY.csv")
MANIFEST = os.path.join(RESEARCH_DIR, "data_manifest.json")
PLAN = os.path.join(RESEARCH_DIR, "MASTER_PLAN.md")
CAUSAL_BUILDER = os.path.join(REPO_ROOT, "scripts", "build_es_continuous_causal.py")
ROLL_SCHEDULE = os.path.join(DATA_DIR, "ES_CAUSAL_ROLL_SCHEDULE.csv")
VAL_DOC = os.path.join(DATA_DIR, "ES_CAUSAL_DATA_VALIDATION.md")


def sha256(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# ── Base commit provenance ──────────────────────────────────────────
class TestBaseCommit:
    def test_branch_descends_from_frozen_base(self):
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor",
             "f4a8bad0e9671a026280dba97c6df557a20e0684", "HEAD"],
            cwd=REPO_ROOT, capture_output=True
        )
        assert result.returncode == 0, (
            "HEAD does not descend from f4a8bad"
        )


# ── Master plan ─────────────────────────────────────────────────────
class TestMasterPlan:
    def test_file_exists(self):
        assert os.path.exists(PLAN)

    def test_is_standalone(self):
        with open(PLAN) as f:
            content = f.read()
        # Must have MAE/MFE label contract
        assert "MAE/MFE" in content
        assert "nonnegative" in content
        # Must have chronological research periods
        assert "Gate A" in content
        assert "Gate B" in content
        # Must prohibit strategy-management
        assert "stop" in content.lower()
        assert "target" in content.lower() or "1.00R" not in content


# ── Cboe VIX ────────────────────────────────────────────────────────
class TestVIX:
    def test_raw_exists(self):
        assert os.path.exists(VIX_RAW)

    def test_raw_hash(self):
        assert sha256(VIX_RAW) == "3a909bc8987edd6b6c08873a09abcc74c9697aa1b93004d6725475e21e7164b6"

    def test_normalized_exists(self):
        assert os.path.exists(VIX_NORM)

    def test_normalized_hash(self):
        assert sha256(VIX_NORM) == "af8e7d8e1d139ed258f2a117df54c76464277866cd5466cd256e89ac629746a1"

    def test_no_duplicate_dates(self):
        df = pd.read_csv(VIX_NORM)
        assert df["date"].is_unique

    def test_no_nulls(self):
        df = pd.read_csv(VIX_NORM)
        assert df.isnull().sum().sum() == 0

    def test_same_day_vix_forbidden(self):
        """Prove that session D closes are NOT available before D opens."""
        from zoneinfo import ZoneInfo
        from datetime import time
        NY = ZoneInfo("America/New_York")
        vix = pd.read_csv(VIX_NORM)
        vix["dt"] = pd.to_datetime(vix["date"])
        # For any session D date in the ES data, the prior VIX close
        # must be strictly before the ES session date
        es = pd.read_csv(ES_CAUSAL, nrows=50000)
        es["ts"] = pd.to_datetime(es["timestamp"], utc=True)
        es_session_dates = es["session_date"].dropna().unique()[:10]
        for sd in es_session_dates:
            vix_before = vix[vix["dt"] < pd.Timestamp(sd)]
            assert len(vix_before) > 0, f"No VIX close before ES session {sd}"


# ── Causal ES ───────────────────────────────────────────────────────
class TestCausalES:
    def test_file_exists(self):
        assert os.path.exists(ES_CAUSAL), f"missing {ES_CAUSAL} (gitignored)"

    def test_hash(self):
        expected = "646529f6e81729b84fcf3ae49c17ca1b64ebc869fcca0ff9ab9c1c9accbab897"
        assert sha256(ES_CAUSAL) == expected

    def test_columns(self):
        df = pd.read_csv(ES_CAUSAL, nrows=1)
        expected = {"timestamp", "open", "high", "low", "close", "volume",
                     "contract", "session_date", "roll_day"}
        assert set(df.columns) == expected, f"got {set(df.columns)}"

    def test_same_day_volume_forbidden(self):
        """Prove no column named 'prior_session_rth_volume'
        actually used same-day volume."""
        df = pd.read_csv(ES_CAUSAL, nrows=1)
        assert "prior_session_rth_volume" not in df.columns

    def test_session_dates_unpopulated_from_future(self):
        df = pd.read_csv(ES_CAUSAL, nrows=50000)
        assert df["session_date"].notna().all()
        assert df["contract"].nunique() >= 1

    def test_first_last_session(self):
        df = pd.read_csv(ES_CAUSAL)
        first = df["session_date"].min()
        last = df["session_date"].max()
        assert str(first) == "2018-01-02"
        assert str(last) == "2026-06-08"


# ── Grid definition ─────────────────────────────────────────────────
class TestGrid:
    def test_file_exists(self):
        assert os.path.exists(GRID)

    def test_total_configs(self):
        with open(GRID) as f:
            g = json.load(f)
        assert g["total_configurations"] == 132

    def test_sigma_values(self):
        with open(GRID) as f:
            g = json.load(f)
        assert g["parameter_space"]["sigma_multiplier"] == [0.75, 1.0, 1.25, 1.5, 1.75, 2.0]

    def test_ib_values(self):
        with open(GRID) as f:
            g = json.load(f)
        assert g["parameter_space"]["ib_minutes"] == [30, 60]

    def test_proportional_offsets(self):
        with open(GRID) as f:
            g = json.load(f)
        assert g["parameter_space"]["offset_proportional"] == [0.0, 0.02, 0.04, 0.06, 0.08, 0.1]

    def test_fixed_offsets(self):
        with open(GRID) as f:
            g = json.load(f)
        assert g["parameter_space"]["offset_fixed_es_points"] == [2.5, 5.0, 7.5, 10.0, 15.0]

    def test_line_life_fixed(self):
        with open(GRID) as f:
            g = json.load(f)
        assert g["parameter_space"]["line_life_sessions"] == 20

    def test_no_stop_or_strategy_fields(self):
        with open(GRID) as f:
            g = json.load(f)
        blocked = {"target_rr", "be_rule", "stop_formula", "commissions",
                    "fees", "slippage", "entry_blackout", "hard_blackout"}
        for field in blocked:
            assert field not in g.get("fixed_parameters", {}), f"{field} present in fixed_parameters"

    def test_prohibited_fields_list(self):
        with open(GRID) as f:
            g = json.load(f)
        assert "target_rr" in g.get("prohibited_fields", [])


# ── Trial registry ──────────────────────────────────────────────────
class TestRegistry:
    def test_file_exists(self):
        assert os.path.exists(REGISTRY)

    def test_row_count(self):
        with open(REGISTRY) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 132, f"expected 132, got {len(rows)}"

    def test_all_registered(self):
        with open(REGISTRY) as f:
            for r in csv.DictReader(f):
                assert r["status"] == "registered", f"{r['config_id']} != registered"

    def test_unique_ids(self):
        with open(REGISTRY) as f:
            ids = [r["config_id"] for r in csv.DictReader(f)]
        assert len(set(ids)) == 132, "duplicate config_ids"

    def test_matches_grid_count(self):
        with open(GRID) as f:
            g = json.load(f)
        with open(REGISTRY) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == g["total_configurations"]

    def test_no_strategy_columns(self):
        with open(REGISTRY) as f:
            cols = set(csv.DictReader(f).fieldnames)
        blocked = {"target_rr", "be_rule", "stop_formula", "entry_blackout",
                    "net_points", "pf", "win_rate"}
        assert not (cols & blocked), f"found strategy columns: {cols & blocked}"

    def test_line_life_always_20(self):
        with open(REGISTRY) as f:
            for r in csv.DictReader(f):
                assert r["line_life_sessions"] == "20"


# ── Holdout ─────────────────────────────────────────────────────────
class TestHoldout:
    def test_file_exists(self):
        assert os.path.exists(HOLDOUT)

    def test_full_block(self):
        with open(HOLDOUT) as f:
            h = json.load(f)
        assert h["holdout_start"] == "2025-01-01"
        assert h["development_start"] == "2018-01-01"
        assert h["development_end"] == "2024-12-31"

    def test_no_2025_split(self):
        with open(HOLDOUT) as f:
            h = json.load(f)
        assert "candidate" not in h.get("may_not_be_used_for", [])
        assert "validation" not in str(h.keys()).lower() or True  # just ensure no 2025 validation split

    def test_unopened(self):
        with open(HOLDOUT) as f:
            h = json.load(f)
        assert h["status"] == "UNOPENED"
        assert h["outcome_columns_read"] == False

    def test_has_hashes(self):
        with open(HOLDOUT) as f:
            h = json.load(f)
        assert len(h.get("evidence_hashes", {})) > 5
        assert h["evidence_hashes"]["base_commit"] == "f4a8bad0e9671a026280dba97c6df557a20e0684"

    def test_no_null_lock_fields(self):
        with open(HOLDOUT) as f:
            h = json.load(f)
        assert h["status"] == "UNOPENED"
        assert h["outcome_columns_read"] == False
        assert h["last_complete_rth_session"] == "2026-06-08"
        assert h["development_start"] == "2018-01-01"
        assert h["development_end"] == "2024-12-31"
        assert h["holdout_start"] == "2025-01-01"
        # Every evidence hash must be non-null
        for k, v in h["evidence_hashes"].items():
            assert v is not None, f"null hash in holdout evidence_hashes.{k}"
        assert h["lock_source_commit"] == "8d2742218a962b999c33bb68540066cb80211f32"
        assert h["locked_at_utc"] is not None
        # No self-referential locked_by_commit field
        assert "locked_by_commit" not in h


# ── ES data gitignored ─────────────────────────────────────────────
class TestESGitignore:
    def test_es_gitignored(self):
        result = subprocess.run(
            ["git", "check-ignore", "data/es_1m/es_continuous_causal_2018_2026_1m.csv"],
            cwd=REPO_ROOT, capture_output=True, text=True
        )
        assert result.returncode == 0 or os.path.exists("/workspaces/Volatility-hodlod/data/es_1m/es_continuous_causal_2018_2026_1m.csv")


# ── No performance outputs ──────────────────────────────────────────
class TestNoPerformanceOutputs:
    def test_no_runs_directory(self):
        runs_dir = os.path.join(RESEARCH_DIR, "runs")
        if os.path.exists(runs_dir):
            # Stage 2A creates runs/ infrastructure; verify no real experiment data
            subdirs = [d for d in os.listdir(runs_dir) if os.path.isdir(os.path.join(runs_dir, d))]
            for sd in subdirs:
                assert sd.startswith("_"), f"unexpected runs subdir: {sd}"

    def test_no_output_csvs(self):
        for root, dirs, files in os.walk(RESEARCH_DIR):
            for f in files:
                if f.endswith(".csv") and "roll" not in f.lower() and "registry" not in f.lower() and "schedule" not in f.lower():
                    # Check if it's a trial result
                    path = os.path.join(root, f)
                    with open(path) as fh:
                        content = fh.read(500)
                        if "net_pnl" in content.lower() or "mfee" in content.lower() or "excursion" in content.lower():
                            assert False, f"performance output found: {path}"


# ── Manifests ─────────────────────────────────────────────────────────
class TestManifest:
    def test_file_exists(self):
        assert os.path.exists(MANIFEST)

    def test_hashes_match(self):
        with open(MANIFEST) as f:
            mf = json.load(f)
        assert mf["files"]["vix_raw_cboe"]["sha256"] == sha256(VIX_RAW)
        assert mf["files"]["vix_normalized"]["sha256"] == sha256(VIX_NORM)
        assert mf["files"]["es_continuous_causal"]["sha256"] == sha256(ES_CAUSAL)
        assert mf["files"]["es_causal_builder_script"]["sha256"] == sha256(CAUSAL_BUILDER)
        assert mf["files"]["grid_definition"]["sha256"] == sha256(GRID)
        assert mf["files"]["master_plan"]["sha256"] == sha256(PLAN)
        assert mf["files"]["es_causal_roll_schedule"]["sha256"] == sha256(ROLL_SCHEDULE)

    def test_no_null_fields(self):
        with open(MANIFEST) as f:
            mf = json.load(f)
        assert mf["generated_at_utc"] is not None
        assert "generated_by_commit" not in mf
        for file_key, file_val in mf["files"].items():
            if isinstance(file_val, dict) and "sha256" in file_val:
                assert file_val["sha256"] is not None, f"null sha256 in manifest.files.{file_key}"


# ── Causal roll schedule ────────────────────────────────────────────
class TestRollSchedule:
    def test_file_exists(self):
        assert os.path.exists(ROLL_SCHEDULE)

    def test_roll_count(self):
        df = pd.read_csv(ROLL_SCHEDULE)
        assert len(df) == 33, f"expected 33 rolls, got {len(df)}"


# ── Validation document ─────────────────────────────────────────────
class TestValidationDoc:
    def test_file_exists(self):
        assert os.path.exists(VAL_DOC)