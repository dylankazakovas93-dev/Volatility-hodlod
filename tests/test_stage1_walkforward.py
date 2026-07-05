"""Outer walk-forward hygiene checks (sections 15, 26): no outer-test year
ever enters training, and 2026 never enters fitting or selection. Run with:

    python3 -m pytest tests/test_stage1_walkforward.py -v
"""
from __future__ import annotations

import ast
import json
import os
import sys

import pandas as pd
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
OUT_DIR = os.path.join(REPO_ROOT, "outputs")

FOLDS = [
    ([2018, 2019, 2020], 2021),
    ([2018, 2019, 2020, 2021], 2022),
    ([2018, 2019, 2020, 2021, 2022], 2023),
    ([2018, 2019, 2020, 2021, 2022, 2023], 2024),
    ([2018, 2019, 2020, 2021, 2022, 2023, 2024], 2025),
]


def test_fold_definitions_never_include_test_year_in_training():
    for train_years, test_year in FOLDS:
        assert test_year not in train_years
        assert max(train_years) == test_year - 1


def test_fold_definitions_never_include_2026():
    for train_years, test_year in FOLDS:
        assert 2026 not in train_years
        assert test_year != 2026


@pytest.fixture(scope="module")
def outer_results():
    p = os.path.join(OUT_DIR, "stage1_outer_test_results.csv")
    if not os.path.exists(p):
        pytest.skip("run scripts/run_stage1_walkforward.py first")
    return pd.read_csv(p)


def test_outer_results_train_years_exclude_2026_and_test_year(outer_results):
    for _, row in outer_results.iterrows():
        train_years = ast.literal_eval(row["train_years"])
        assert 2026 not in train_years
        assert row["test_year"] not in train_years


@pytest.fixture(scope="module")
def learned_walkforward():
    p = os.path.join(OUT_DIR, "stage1_learned_walkforward.csv")
    if not os.path.exists(p):
        pytest.skip("run scripts/fit_stage1_excursion_formulas.py first")
    return pd.read_csv(p)


def test_learned_folds_never_train_on_2026(learned_walkforward):
    for _, row in learned_walkforward.iterrows():
        train_years = ast.literal_eval(row["train_years"])
        assert 2026 not in train_years
        assert row["test_year"] not in train_years


def test_learned_coefficient_bounds_respected(learned_walkforward):
    for _, row in learned_walkforward.iterrows():
        tp_coefs = json.loads(row["tp_coefs"])
        sl_coefs = json.loads(row["sl_coefs"])
        for name, val in {**tp_coefs, **sl_coefs}.items():
            if name.startswith("log1p_"):
                assert val >= -1e-9
            elif name == "log_rvol60":
                assert -0.30 - 1e-9 <= val <= 0.30 + 1e-9


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
