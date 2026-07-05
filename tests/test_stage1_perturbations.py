"""Perturbation-list hygiene (section 26: perturbation values come only
from the predefined list; no candidate/value added after seeing results).
Run with:

    python3 -m pytest tests/test_stage1_perturbations.py -v
"""
from __future__ import annotations

import glob
import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
OUT_DIR = os.path.join(REPO_ROOT, "outputs")

from scripts.run_stage1_perturbations import (  # noqa: E402
    RVOL_HIST_OPTIONS, CLIP_OPTIONS, COST_OPTIONS,
)
from scripts.run_stage1_simple_surface import GAMMAS, MULTS  # noqa: E402


def test_preregistered_lists_match_spec():
    assert RVOL_HIST_OPTIONS == [15, 20, 30]
    assert CLIP_OPTIONS == [(0.75, 1.33), (0.80, 1.25), (0.85, 1.18)]
    assert COST_OPTIONS == [0.5, 1.0, 2.0]
    assert GAMMAS == [-0.30, -0.15, 0.00, 0.15, 0.30]
    assert MULTS == [0.50, 0.75, 1.00, 1.25, 1.50, 1.75, 2.00]


def test_any_committed_perturbation_files_only_use_preregistered_neighbor_values():
    files = glob.glob(os.path.join(OUT_DIR, "stage1_perturbations_*.csv"))
    if not files:
        pytest.skip("no perturbation runs committed yet")
    for path in files:
        df = pd.read_csv(path)
        for name in df["perturbation"]:
            if name.startswith("a_neighbor_"):
                val = float(name.rsplit("_", 1)[1])
                assert val in MULTS
            elif name.startswith("b_neighbor_"):
                val = float(name.rsplit("_", 1)[1])
                assert val in MULTS
            elif name.startswith("gamma_neighbor_"):
                val = float(name.rsplit("_", 1)[1])
                assert any(abs(val - g) < 1e-9 for g in GAMMAS)
            elif name.startswith("rvol_history_"):
                val = int(name.rsplit("_", 1)[1])
                assert val in RVOL_HIST_OPTIONS
            elif name.startswith("cost_"):
                val = float(name.rsplit("_", 1)[1])
                assert val in COST_OPTIONS


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
