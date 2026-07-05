"""Machine-verifiable invariants for the NQ strict one-position reconciliation.

Run with:
    /root/.local/bin/pytest tests/test_nq_strict_invariants.py -v

These tests fail loudly on any drift from the frozen canonical config
(configs/nq_canonical_strict.yaml) or from the physical-touch / skip / SAL /
overlap invariants the strict engine is required to satisfy. They read the
already-generated outputs/ CSVs plus the canonical data files directly --
they do not re-run the multi-minute simulation themselves except where noted.
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

CONFIG_PATH = os.path.join(REPO_ROOT, "configs", "nq_canonical_strict.yaml")
OUT_DIR = os.path.join(REPO_ROOT, "outputs")


@pytest.fixture(scope="module")
def config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _read_with_ts(path, ts_cols):
    df = pd.read_csv(path)
    for c in ts_cols:
        df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    return df


@pytest.fixture(scope="module")
def executed(config):
    return _read_with_ts(os.path.join(OUT_DIR, "nq_strict_executed.csv"),
                          ["entry_time", "exit_time"])


@pytest.fixture(scope="module")
def skipped(config):
    return _read_with_ts(os.path.join(OUT_DIR, "nq_strict_skipped.csv"),
                          ["physical_touch", "entry_time", "exit_time"])


@pytest.fixture(scope="module")
def physical_touches(config):
    return pd.read_csv(os.path.join(OUT_DIR, "nq_physical_first_touches.csv"))


@pytest.fixture(scope="module")
def yearly(config):
    return pd.read_csv(os.path.join(OUT_DIR, "nq_strict_yearly.csv"))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------- data gates

def test_canonical_bar_count(config):
    bars_path = os.path.join(REPO_ROOT, config["data"]["bars_file"])
    with open(bars_path) as f:
        n = sum(1 for _ in f) - 1  # minus header
    assert n == config["data"]["bars_rows"] == 2964655


def test_canonical_data_hashes(config):
    bars_path = os.path.join(REPO_ROOT, config["data"]["bars_file"])
    vxn_path = os.path.join(REPO_ROOT, config["data"]["vxn_file"])
    assert sha256_file(bars_path) == config["data"]["bars_sha256"]
    assert sha256_file(vxn_path) == config["data"]["vxn_sha256"]


def test_eligible_candidate_gate(config):
    from volgen.levels import NQ_PARAMS, generate_levels, load_1m_ohlcv, load_gvz_daily
    import scripts.build_be60_enriched  # noqa: F401  (ensures import path works)
    import scripts.nq_cond_be45 as C

    bars_path = os.path.join(REPO_ROOT, config["data"]["bars_file"])
    vxn_path = os.path.join(REPO_ROOT, config["data"]["vxn_file"])
    bars = load_1m_ohlcv(bars_path)
    vxn = load_gvz_daily(vxn_path)
    raw = C.build_ledger(bars, vxn)
    assert len(raw) == config["candidate_gate"]["eligible_count"] == 1841


# ------------------------------------------------------- frozen headline numbers

def test_executed_count(executed, config):
    assert len(executed) == config["frozen_primary_result"]["executed_trades"] == 1107


def test_net_points_within_tolerance(executed, config):
    tol = config["frozen_primary_result"]["numerical_tolerance"]["net_pts"]
    net = executed["pnl"].sum()
    expected = config["frozen_primary_result"]["net_pts"]
    assert abs(net - expected) <= tol, f"net={net} expected={expected}+/-{tol}"


def test_profit_factor_within_tolerance(executed, config):
    pnl = executed["pnl"]
    g = float(pnl[pnl > 0].sum())
    l = float(-pnl[pnl < 0].sum())
    pf = g / l if l > 0 else float("inf")
    tol = config["frozen_primary_result"]["numerical_tolerance"]["PF"]
    expected = config["frozen_primary_result"]["PF"]
    assert abs(pf - expected) <= tol, f"PF={pf} expected={expected}+/-{tol}"


def test_exit_reason_counts(executed, config):
    counts = executed["exit_reason"].value_counts()
    fr = config["frozen_primary_result"]
    assert int(counts.get("TP", 0)) == fr["TP"] == 394
    assert int(counts.get("SL", 0)) == fr["SL"] == 333
    assert int(counts.get("BE", 0)) == fr["BE"] == 281
    assert int(counts.get("cutoff", 0)) == fr["cutoff"] == 99


def test_negative_years_exact(yearly, config):
    neg = sorted(yearly[yearly["net_pts"] < 0]["year"].astype(int).tolist())
    assert neg == config["frozen_primary_result"]["negative_years"] == [2019, 2023, 2024]


def test_annual_pnl_sums_to_total(executed, yearly):
    total_from_yearly = yearly["net_pts"].sum()
    total_from_trades = executed["pnl"].sum()
    assert abs(total_from_yearly - total_from_trades) < 0.1


def test_pf_includes_cutoff_outcomes(executed):
    cutoffs = executed[executed["exit_reason"] == "cutoff"]
    assert len(cutoffs) > 0
    # PF computed over ALL exit reasons must differ from PF computed while
    # excluding cutoff rows, proving cutoff PnL is actually included.
    pnl_all = executed["pnl"]
    pnl_no_cutoff = executed[executed["exit_reason"] != "cutoff"]["pnl"]

    def pf(s):
        g, l = float(s[s > 0].sum()), float(-s[s < 0].sum())
        return g / l if l > 0 else float("inf")

    assert pf(pnl_all) != pf(pnl_no_cutoff)


# --------------------------------------------------------- structural invariants

def test_no_level_id_executes_twice(executed):
    dupes = executed["level_id"][executed["level_id"].duplicated()]
    assert dupes.empty, f"level_ids executed more than once: {dupes.tolist()}"


def test_no_skipped_touch_becomes_later_entry(executed, skipped):
    executed_ids = set(executed["level_id"])
    skipped_ids = set(skipped[skipped["eligibility"] == "skipped"]["level_id"])
    overlap = executed_ids & skipped_ids
    assert overlap == set(), f"level_ids both skipped and executed: {overlap}"


def test_no_overlapping_positions(executed):
    ex = executed.sort_values("entry_time").reset_index(drop=True)
    for i in range(1, len(ex)):
        prev_exit = ex.loc[i - 1, "exit_time"]
        this_entry = ex.loc[i, "entry_time"]
        assert this_entry >= prev_exit, (
            f"overlap: trade {i-1} exits {prev_exit} but trade {i} enters {this_entry}"
        )


def test_no_same_bar_exit_reentry(executed):
    ex = executed.sort_values("entry_time").reset_index(drop=True)
    for i in range(1, len(ex)):
        prev_exit = ex.loc[i - 1, "exit_time"]
        this_entry = ex.loc[i, "entry_time"]
        assert this_entry != prev_exit, (
            f"same-bar re-entry at {this_entry} (primary config blocks this)"
        )


def test_no_blocked_time_entries(executed):
    et = executed["entry_time"].dt.tz_convert("America/New_York")
    minutes = et.dt.hour * 60 + et.dt.minute
    blocked = minutes[(minutes >= 11 * 60) & (minutes < 15 * 60)]
    assert blocked.empty, f"entries inside the blocked 11:00-15:00 ET window: {len(blocked)}"


def test_sal_never_activates_before_a_losing_exit(executed):
    """For every trade following a real loss (pnl<-0.1, exit!=BE) within the
    same session, its entry_time must be >= the loss's exit_time (SAL is
    time-aware, never retroactive) -- already implied by no-overlap, but
    checked explicitly here against the SAL semantics."""
    ex = executed.sort_values("entry_time").reset_index(drop=True)
    for i in range(1, len(ex)):
        prev = ex.loc[i - 1]
        if prev["pnl"] < -0.1 and prev["exit_reason"] != "BE":
            assert ex.loc[i, "entry_time"] >= prev["exit_time"]


def test_skip_categories_reconcile_to_physical_touch_population(executed, skipped, physical_touches):
    n_touched_physical = physical_touches["touched_at"].notna().sum()
    n_executed = len(executed)
    n_skipped = len(skipped[skipped["eligibility"] == "skipped"])
    assert n_executed + n_skipped == n_touched_physical, (
        f"executed({n_executed}) + skipped({n_skipped}) != "
        f"physical touches({n_touched_physical})"
    )


def test_exit_price_is_populated(executed):
    assert executed["exit_price"].notna().all()
    assert executed["entry_price"].notna().all()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
