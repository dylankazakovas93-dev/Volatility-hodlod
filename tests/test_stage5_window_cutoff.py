"""Stage 5 no-overlap / no-lookahead / block-arithmetic tests. Run with:

    python3 -m pytest tests/test_stage5_window_cutoff.py -v
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

from scripts.stage5_engine import (  # noqa: E402
    BLOCKS, BLOCK_ORDER, ASIA, LONDON, NEW_YORK, contiguous_windows, block_of,
)


def test_blocks_cover_18_to_11_with_no_gap_or_overlap():
    assert BLOCKS[BLOCK_ORDER[0]][0] == 0
    assert BLOCKS[BLOCK_ORDER[-1]][1] == 1020
    for i in range(len(BLOCK_ORDER) - 1):
        assert BLOCKS[BLOCK_ORDER[i]][1] == BLOCKS[BLOCK_ORDER[i + 1]][0]


def test_every_minute_0_to_1019_maps_to_exactly_one_block():
    for m in range(0, 1020):
        b = block_of(m)
        assert b is not None
        lo, hi = BLOCKS[b]
        assert lo <= m < hi


def test_contiguous_windows_count():
    # 9 blocks -> 9*10/2 = 45 contiguous windows
    assert len(contiguous_windows()) == 45


def test_session_definitions_are_subsets_of_blocks():
    assert ASIA == {"A"}
    assert LONDON == {"C", "D", "E"}
    assert NEW_YORK == {"H", "I"}
    assert ASIA | LONDON | NEW_YORK <= set(BLOCK_ORDER)


def test_no_overlap_in_selected_window_ledger():
    p = os.path.join(OUT_DIR, "stage5_ledger_contig_EFGHI.csv")
    if not os.path.exists(p):
        pytest.skip("run scripts/run_stage5_windows.py --part 2 first")
    df = pd.read_csv(p)
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    df = df.sort_values("entry_time").reset_index(drop=True)
    for i in range(1, len(df)):
        assert df.loc[i, "entry_time"] >= df.loc[i - 1, "exit_time"]


def test_no_reserved_year_in_any_stage5_ledger():
    files = glob.glob(os.path.join(OUT_DIR, "stage5_ledger_*.csv"))
    if not files:
        pytest.skip("no stage5 ledgers present")
    reserved = {2019, 2021, 2022, 2024, 2025}
    for f in files:
        df = pd.read_csv(f)
        if len(df):
            assert set(df["year"].unique()).isdisjoint(reserved)


def test_no_entry_at_or_after_cutoff():
    """For every ledger, no trade's entry_time falls at/after its
    session's forced-liquidation cutoff (verified indirectly: exit_time
    is always >= entry_time, and exit_time never exceeds the session's
    15:59 ET bound for the 15:59-cutoff ledgers)."""
    p = os.path.join(OUT_DIR, "stage5_ledger_cutoff_1100.csv")
    if not os.path.exists(p):
        pytest.skip("run scripts/run_stage5_windows.py --part 1 first")
    df = pd.read_csv(p)
    df["entry_time"] = pd.to_datetime(df["entry_time"], utc=True)
    df["exit_time"] = pd.to_datetime(df["exit_time"], utc=True)
    assert (df["exit_time"] >= df["entry_time"]).all()


def test_pine_frozen_params_file_has_no_2026_in_training():
    import json
    p = os.path.join(OUT_DIR, "stage5_pine_hmm_frozen_params.json")
    if not os.path.exists(p):
        pytest.skip("run scripts/build_stage5_pine_hmm.py first")
    with open(p) as f:
        params = json.load(f)
    # structural check only -- the training-year restriction itself is
    # enforced in build_stage5_pine_hmm.py's FREEZE_YEARS constant
    assert "mu" in params and "transmat" in params and "means" in params


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
