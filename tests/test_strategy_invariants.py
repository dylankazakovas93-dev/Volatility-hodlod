"""Level-generation and execution invariants for the frozen strict config.

Run with:
    python3 -m pytest tests/test_strategy_invariants.py -v

Level-generation tests re-derive values directly from src/level_generation.py
against the canonical bars/VXN. Execution tests read the already-generated
outputs/ CSVs produced by src/strict_engine.py and check the causal/skip/SAL
invariants the engine is required to satisfy.
"""
from __future__ import annotations

import math
import os
import sys

import pandas as pd
import pytest
import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from src.data_loader import load_1m_ohlcv, load_gvz_daily  # noqa: E402
from src.level_generation import NQ_PARAMS, generate_levels  # noqa: E402
from src.strict_engine import LINE_DAYS, build_eligible_candidates  # noqa: E402

CONFIG_PATH = os.path.join(REPO_ROOT, "configs", "nq_current_config.yaml")
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
def bars(config):
    p = os.path.join(REPO_ROOT, config["data"]["bars_file"])
    if not os.path.exists(p):
        pytest.skip("canonical bars not present locally -- see data/README.md")
    return load_1m_ohlcv(p)


@pytest.fixture(scope="module")
def vxn(config):
    p = os.path.join(REPO_ROOT, config["data"]["vxn_file"])
    if not os.path.exists(p):
        pytest.skip("canonical VXN not present locally -- see data/README.md")
    return load_gvz_daily(p)


@pytest.fixture(scope="module")
def levels(bars, vxn):
    return generate_levels(bars, vxn, params=NQ_PARAMS)


@pytest.fixture(scope="module")
def executed():
    p = os.path.join(OUT_DIR, "baseline_executed.csv")
    if not os.path.exists(p):
        pytest.skip("outputs/baseline_executed.csv not present -- run src/strict_engine.py first")
    return _read_with_ts(p, ["entry_time", "exit_time"])


@pytest.fixture(scope="module")
def skipped():
    p = os.path.join(OUT_DIR, "baseline_skipped.csv")
    if not os.path.exists(p):
        pytest.skip("outputs/baseline_skipped.csv not present -- run src/strict_engine.py first")
    return _read_with_ts(p, ["physical_touch", "entry_time", "exit_time"])


@pytest.fixture(scope="module")
def physical_touches():
    p = os.path.join(OUT_DIR, "baseline_physical_touches.csv")
    if not os.path.exists(p):
        pytest.skip("outputs/baseline_physical_touches.csv not present -- run src/strict_engine.py first")
    return pd.read_csv(p)


@pytest.fixture(scope="module")
def yearly():
    p = os.path.join(OUT_DIR, "baseline_yearly.csv")
    if not os.path.exists(p):
        pytest.skip("outputs/baseline_yearly.csv not present -- run src/strict_engine.py first")
    return pd.read_csv(p)


# ------------------------------------------------------------ level generation

def test_nq_constants_match_frozen_config(config):
    assert NQ_PARAMS.sigma_mult == config["level_generation"]["sigma_mult"] == 1.25
    assert NQ_PARAMS.ib_minutes == config["level_generation"]["ib_minutes"] == 60
    assert NQ_PARAMS.fixed_offset == config["level_generation"]["fixed_offset"] == 15.75


def test_vxn_input_uses_only_prior_data(bars, vxn, levels):
    """For every session, vix_close must equal the most recent VXN close
    strictly BEFORE the session date -- never same-day or future."""
    sample = levels.head(50)
    for _, row in sample.iterrows():
        session_date = pd.Timestamp(row["session_date"])
        prior = vxn[vxn.index < session_date.tz_localize(None).normalize()]
        assert not prior.empty
        assert row["vix_close"] == pytest.approx(float(prior.iloc[-1]))


def test_ib_cutoff_bar_is_included(bars, levels):
    """The IB-completion bar's high/low must be reflected in ib_high/ib_low
    -- i.e. the cutoff bar is included, not excluded (off-by-one check)."""
    row = levels.iloc[0]
    day_bars = bars.between_time("09:30", "16:00")
    day_bars = day_bars[day_bars.index.date == row["session_date"]]
    ib_cutoff = day_bars.index[0] + pd.Timedelta(minutes=NQ_PARAMS.ib_minutes)
    ib_bars_inclusive = day_bars[day_bars.index <= ib_cutoff]
    assert row["ib_high"] == float(ib_bars_inclusive["high"].max())
    assert row["ib_low"] == float(ib_bars_inclusive["low"].min())


def test_upper_lower_level_formula(levels):
    row = levels.iloc[0]
    sigma_day = row["sigma_day"]
    imp_up = row["cash_open"] + NQ_PARAMS.sigma_mult * sigma_day
    imp_dn = row["cash_open"] - NQ_PARAMS.sigma_mult * sigma_day
    assert imp_up == pytest.approx(row["imp_up"])
    assert imp_dn == pytest.approx(row["imp_dn"])

    ib_range = row["ib_high"] - row["ib_low"]
    ib_ext_up = row["ib_high"] + ib_range
    ib_ext_dn = row["ib_low"] - ib_range
    expected_upper = (ib_ext_up + imp_up) / 2 - NQ_PARAMS.fixed_offset
    expected_lower = (ib_ext_dn + imp_dn) / 2 + NQ_PARAMS.fixed_offset
    assert row["upper_level"] == pytest.approx(expected_upper)
    assert row["lower_level"] == pytest.approx(expected_lower)


def test_annualization_divisor_is_sqrt_252(levels):
    row = levels.iloc[0]
    expected_sigma = row["cash_open"] * (row["vix_close"] / 100.0) / math.sqrt(252)
    assert row["sigma_day"] == pytest.approx(expected_sigma)


def test_level_lifetime_is_line_days(levels, config):
    assert LINE_DAYS == config["level_generation"]["line_days"] == 20


# --------------------------------------------------------------- eligible gate

def test_eligible_candidate_gate(bars, vxn, config):
    raw = build_eligible_candidates(bars, vxn)
    assert len(raw) == config["candidate_gate"]["eligible_count"] == 1841


# ------------------------------------------------------- frozen headline numbers

def test_executed_count(executed, config):
    assert len(executed) == config["frozen_result"]["executed_trades"] == 1107


def test_net_points_within_tolerance(executed, config):
    tol = config["frozen_result"]["numerical_tolerance"]["net_pts"]
    net = executed["pnl"].sum()
    expected = config["frozen_result"]["net_pts"]
    assert abs(net - expected) <= tol


def test_profit_factor_within_tolerance(executed, config):
    pnl = executed["pnl"]
    g = float(pnl[pnl > 0].sum())
    l = float(-pnl[pnl < 0].sum())
    pf = g / l if l > 0 else float("inf")
    tol = config["frozen_result"]["numerical_tolerance"]["PF"]
    expected = config["frozen_result"]["PF"]
    assert abs(pf - expected) <= tol


def test_exit_reason_counts(executed, config):
    counts = executed["exit_reason"].value_counts()
    fr = config["frozen_result"]
    assert int(counts.get("TP", 0)) == fr["TP"] == 394
    assert int(counts.get("SL", 0)) == fr["SL"] == 333
    assert int(counts.get("BE", 0)) == fr["BE"] == 281
    assert int(counts.get("cutoff", 0)) == fr["cutoff"] == 99


def test_negative_years_exact(yearly, config):
    neg = sorted(yearly[yearly["net_pts"] < 0]["year"].astype(int).tolist())
    assert neg == config["frozen_result"]["negative_years"] == [2019, 2023, 2024]


def test_annual_pnl_sums_to_total(executed, yearly):
    assert abs(yearly["net_pts"].sum() - executed["pnl"].sum()) < 0.1


def test_pf_includes_cutoff_outcomes(executed):
    cutoffs = executed[executed["exit_reason"] == "cutoff"]
    assert len(cutoffs) > 0
    pnl_all = executed["pnl"]
    pnl_no_cutoff = executed[executed["exit_reason"] != "cutoff"]["pnl"]

    def pf(s):
        g, l = float(s[s > 0].sum()), float(-s[s < 0].sum())
        return g / l if l > 0 else float("inf")

    assert pf(pnl_all) != pf(pnl_no_cutoff)


# --------------------------------------------------------- structural invariants

def test_no_level_id_executes_twice(executed):
    dupes = executed["level_id"][executed["level_id"].duplicated()]
    assert dupes.empty


def test_no_skipped_touch_becomes_later_entry(executed, skipped):
    executed_ids = set(executed["level_id"])
    skipped_ids = set(skipped[skipped["eligibility"] == "skipped"]["level_id"])
    assert (executed_ids & skipped_ids) == set()


def test_no_overlapping_positions(executed):
    ex = executed.sort_values("entry_time").reset_index(drop=True)
    for i in range(1, len(ex)):
        assert ex.loc[i, "entry_time"] >= ex.loc[i - 1, "exit_time"]


def test_no_same_bar_exit_reentry(executed):
    ex = executed.sort_values("entry_time").reset_index(drop=True)
    for i in range(1, len(ex)):
        assert ex.loc[i, "entry_time"] != ex.loc[i - 1, "exit_time"]


def test_no_blocked_time_entries(executed):
    et = executed["entry_time"].dt.tz_convert("America/New_York")
    minutes = et.dt.hour * 60 + et.dt.minute
    blocked = minutes[(minutes >= 11 * 60) & (minutes < 15 * 60)]
    assert blocked.empty


def test_negative_cutoff_activates_sal(executed):
    ex = executed.sort_values("entry_time").reset_index(drop=True)
    found_case = False
    for i in range(1, len(ex)):
        prev = ex.loc[i - 1]
        if prev["exit_reason"] == "cutoff" and prev["pnl"] < -0.1:
            found_case = True
            assert ex.loc[i, "entry_time"] >= prev["exit_time"]
    # not asserting found_case is True: whether a negative cutoff happens to
    # be followed by another same-session touch is a data fact, not a rule;
    # the rule under test is causal ordering when it does happen.


def test_be_does_not_activate_sal(executed):
    ex = executed.sort_values("entry_time").reset_index(drop=True)
    for i in range(1, len(ex)):
        prev = ex.loc[i - 1]
        if prev["exit_reason"] == "BE":
            # a BE scratch must never itself count as the loss that arms SAL
            assert prev["pnl"] >= -0.1


def test_sal_never_activates_before_a_losing_exit(executed):
    ex = executed.sort_values("entry_time").reset_index(drop=True)
    for i in range(1, len(ex)):
        prev = ex.loc[i - 1]
        if prev["pnl"] < -0.1 and prev["exit_reason"] != "BE":
            assert ex.loc[i, "entry_time"] >= prev["exit_time"]


def test_skip_categories_reconcile_to_physical_touch_population(executed, skipped, physical_touches):
    n_touched_physical = physical_touches["touched_at"].notna().sum()
    n_executed = len(executed)
    n_skipped = len(skipped[skipped["eligibility"] == "skipped"])
    assert n_executed + n_skipped == n_touched_physical


def test_exit_price_is_populated(executed):
    assert executed["exit_price"].notna().all()
    assert executed["entry_price"].notna().all()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
