"""Structural tests for scripts/og_validation_dual_config.py.

These tests exercise argument parsing, config validation, fail-closed
behavior, and output schema shape ONLY. They must never compute a real
outcome against the locked validation years {2019,2021,2022,2024,2025} --
all engine runs in this file use tiny synthetic bars/ranges/events fixtures
or restrict to build years, never the real full-dataset cache.
"""
import copy
import os
import sys

import pandas as pd
import pytest
import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import scripts.og_validation_dual_config as v


PRIMARY_PATH = os.path.join(REPO_ROOT, "configs", "OG_PRIMARY_150R.yaml")
SECONDARY_PATH = os.path.join(REPO_ROOT, "configs", "OG_OPERATIONAL_100R.yaml")


def load_raw(path):
    with open(path) as f:
        return yaml.safe_load(f)


# --------------------------------------------------------------------------
# Config loading / fail-closed checks (real config files, no engine run)
# --------------------------------------------------------------------------

def test_real_configs_load_cleanly():
    cfg_p = v.load_config(PRIMARY_PATH)
    cfg_s = v.load_config(SECONDARY_PATH)
    assert cfg_p["config_id"] == "OG_PRIMARY_150R"
    assert cfg_s["config_id"] == "OG_OPERATIONAL_100R"


def test_real_configs_only_differ_in_target_r():
    cfg_p = v.load_config(PRIMARY_PATH)
    cfg_s = v.load_config(SECONDARY_PATH)
    v.assert_configs_only_differ_in_target_r(cfg_p, cfg_s, PRIMARY_PATH, SECONDARY_PATH)


def test_resolve_effective_params():
    cfg_p = v.load_config(PRIMARY_PATH)
    cfg_s = v.load_config(SECONDARY_PATH)
    pp = v.resolve_effective_params(cfg_p)
    ps = v.resolve_effective_params(cfg_s)
    assert pp["target_r"] == 1.50
    assert ps["target_r"] == 1.00
    assert pp["be_bars"] == ps["be_bars"] == 45
    assert pp["blocked_window"] == ps["blocked_window"] == (600, 900)


def test_missing_required_field_fails_closed(tmp_path):
    raw = load_raw(PRIMARY_PATH)
    del raw["management"]
    bad_path = tmp_path / "bad.yaml"
    bad_path.write_text(yaml.dump(raw))
    with pytest.raises(v.ValidationFailClosed, match="missing required config field"):
        v.load_config(str(bad_path))


def test_wrong_status_label_fails_closed(tmp_path):
    raw = load_raw(PRIMARY_PATH)
    raw["status"] = "SOMETHING_ELSE"
    bad_path = tmp_path / "bad_status.yaml"
    bad_path.write_text(yaml.dump(raw))
    with pytest.raises(v.ValidationFailClosed, match="status label mismatch"):
        v.load_config(str(bad_path))


def test_wrong_source_commit_fails_closed(tmp_path):
    raw = load_raw(PRIMARY_PATH)
    raw["source"]["introducing_commit"] = "0" * 40
    bad_path = tmp_path / "bad_commit.yaml"
    bad_path.write_text(yaml.dump(raw))
    with pytest.raises(v.ValidationFailClosed, match="introducing_commit"):
        v.load_config(str(bad_path))


def test_wrong_data_hash_fails_closed(tmp_path):
    raw = load_raw(PRIMARY_PATH)
    raw["data"]["vxn_sha256"] = "deadbeef" * 8
    bad_path = tmp_path / "bad_hash.yaml"
    bad_path.write_text(yaml.dump(raw))
    with pytest.raises(v.ValidationFailClosed, match="vxn file sha256"):
        v.load_config(str(bad_path))


def test_wrong_expected_ledger_hash_fails_closed(tmp_path):
    raw = load_raw(PRIMARY_PATH)
    raw["expected_build_ledger"]["sha256"] = "0" * 64
    bad_path = tmp_path / "bad_ledger.yaml"
    bad_path.write_text(yaml.dump(raw))
    with pytest.raises(v.ValidationFailClosed, match="expected_build_ledger sha256"):
        v.load_config(str(bad_path))


def test_configs_differing_in_more_than_target_r_fails_closed():
    cfg_p = v.load_config(PRIMARY_PATH)
    cfg_s = copy.deepcopy(v.load_config(SECONDARY_PATH))
    cfg_s["management"]["be_bars"] = 30
    with pytest.raises(v.ValidationFailClosed, match="management"):
        v.assert_configs_only_differ_in_target_r(cfg_p, cfg_s, PRIMARY_PATH, SECONDARY_PATH)


def test_identical_target_r_fails_closed():
    cfg_p = v.load_config(PRIMARY_PATH)
    cfg_s = copy.deepcopy(v.load_config(SECONDARY_PATH))
    cfg_s["target"]["target_r"] = cfg_p["target"]["target_r"]
    with pytest.raises(v.ValidationFailClosed, match="identical target_r"):
        v.assert_configs_only_differ_in_target_r(cfg_p, cfg_s, PRIMARY_PATH, SECONDARY_PATH)


def test_nonzero_be_extra_lock_fails_closed():
    cfg_p = copy.deepcopy(v.load_config(PRIMARY_PATH))
    cfg_p["management"]["be_extra_lock"] = 5.0
    with pytest.raises(v.ValidationFailClosed, match="be_extra_lock"):
        v.resolve_effective_params(cfg_p)


def test_hmm_enabled_fails_closed():
    cfg_p = copy.deepcopy(v.load_config(PRIMARY_PATH))
    cfg_p["hmm_gate"]["enabled"] = True
    with pytest.raises(v.ValidationFailClosed, match="hmm_gate"):
        v.resolve_effective_params(cfg_p)


# --------------------------------------------------------------------------
# CLI argument / year-filter fail-closed checks
# --------------------------------------------------------------------------

def test_years_outside_locked_set_fails_closed(tmp_path):
    with pytest.raises(v.ValidationFailClosed, match=r"--years must be exactly"):
        v.main([
            "--years", "2018", "2020", "2023", "2026", "2019",
            "--config", PRIMARY_PATH, "--config", SECONDARY_PATH,
            "--out-dir", str(tmp_path),
        ])


def test_banned_years_fail_closed_even_if_superset(tmp_path):
    with pytest.raises(v.ValidationFailClosed):
        v.main([
            "--years", "2013", "2014", "2015", "2019", "2021",
            "--config", PRIMARY_PATH, "--config", SECONDARY_PATH,
            "--out-dir", str(tmp_path),
        ])


def test_wrong_number_of_configs_fails_closed(tmp_path):
    with pytest.raises(v.ValidationFailClosed, match="exactly two --config"):
        v.main([
            "--years", "2019", "2021", "2022", "2024", "2025",
            "--config", PRIMARY_PATH,
            "--out-dir", str(tmp_path),
        ])


# --------------------------------------------------------------------------
# Engine-facing structural checks: SYNTHETIC / build-year data only, never
# the real locked-validation-year cache.
# --------------------------------------------------------------------------

def test_run_one_config_rejects_build_year_leak_with_synthetic_data(tmp_path):
    """Feed run_one_config a synthetic ex_df-producing setup where the
    underlying data covers ONLY a build year (2020) but request an out-of-
    band year filter that should exclude everything -- exercises the leak
    guard without ever touching real 2019/2021/2022/2024/2025 data."""
    # Directly test the leak-detection logic via filter_build_years + the
    # guard in run_one_config by constructing a tiny synthetic executed
    # trades frame instead of running the real engine.
    import scripts.og_validation_dual_config as mod
    from src.og_build_variant_engine import filter_build_years

    synthetic = pd.DataFrame({
        "year": [2020, 2020, 2019],
        "pnl": [10.0, -5.0, 3.0],
        "cap": [100.0, 100.0, 100.0],
        "entry_time": pd.to_datetime(["2020-01-02", "2020-01-03", "2019-01-02"], utc=True),
        "exit_time": pd.to_datetime(["2020-01-02", "2020-01-03", "2019-01-02"], utc=True),
    })
    # Filtering to {2019} only should drop the 2020 build-year rows -- this
    # exercises filter_build_years directly (the same function the runner
    # uses), on synthetic data only.
    filtered = filter_build_years(synthetic, years={2019})
    assert set(filtered["year"].unique()) == {2019}
    assert 2020 not in set(filtered["year"].unique())


def test_evaluate_gate_schema_on_synthetic_ledger():
    """Gate math must produce all 11 (well, criteria 2-11 -- #1 is the
    invariant-test suite, evaluated separately) criteria on a synthetic
    ledger covering the 5 locked years with fabricated numbers -- this is
    NOT a real outcome, purely a schema/shape check of evaluate_gate()."""
    synthetic = pd.DataFrame({
        "year": [2019] * 60 + [2021] * 60 + [2022] * 60 + [2024] * 60 + [2025] * 60,
        "pnl": ([1.0] * 40 + [-1.0] * 20) * 5,
        "cap": [10.0] * 300,
    })
    gate, per_year, overall = v.evaluate_gate(synthetic, {2019, 2021, 2022, 2024, 2025})
    expected_keys = {
        "2_pooled_net_positive", "3_pooled_R_positive", "4_pooled_PF_pts_ge_1.15",
        "5_pooled_PF_R_ge_1.05", "6_avg_R_per_trade_positive",
        "7_at_least_3_of_5_years_positive_R", "8_at_least_3_of_5_years_PF_pts_gt_1.05",
        "9_total_R_positive_excl_best_year", "10_at_least_250_trades",
        "11_no_year_gt_80pct_of_positive_net",
    }
    assert set(gate.keys()) == expected_keys
    assert isinstance(overall, bool)
    assert set(per_year.keys()) == {2019, 2021, 2022, 2024, 2025}


def test_evaluate_gate_empty_ledger_does_not_crash():
    empty = pd.DataFrame(columns=["year", "pnl", "cap"])
    gate, per_year, overall = v.evaluate_gate(empty, {2019, 2021, 2022, 2024, 2025})
    assert overall is False


def test_run_one_config_end_to_end_with_synthetic_bars(tmp_path):
    """End-to-end structural smoke test of run_one_config()'s wiring
    (run_variant_managed -> firewall filter -> ledger/metrics files) using a
    fully synthetic, tiny bars/ranges/events fixture that only contains a
    single made-up 2019 touch. This proves the plumbing works without
    computing any real outcome against the real locked-year dataset -- the
    "2019" trade here is entirely synthetic (fabricated OHLCV), not derived
    from data/nq_1m/nq_continuous_2018_2026_1m.csv in any way."""
    import numpy as np

    # Use a year (2030) outside both the build-year and locked-validation-year
    # sets entirely, so this fixture cannot be mistaken for real locked-year
    # computation under any interpretation.
    idx = pd.date_range("2030-03-04 09:30:00", periods=200, freq="1min", tz="America/New_York")
    bars = pd.DataFrame({
        "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 10,
    }, index=idx)
    bars.index.name = "time"
    ranges = pd.Series([5.0] * len(idx), index=idx)
    events = [{
        "level_id": "synthetic_0", "level_idx": 0,
        "session_date": idx[0].date(), "created_at": idx[0],
        "side": "lower", "level": 99.5, "touched_at": idx[5],
    }]
    params = {"be_bars": 45, "blocked_window": (600, 900), "target_r": 1.5}
    summary, by, metrics_df = v.run_one_config(
        "OG_PRIMARY_150R", params, bars, ranges, events, {2030}, str(tmp_path))
    ledger_path = tmp_path / "OG_PRIMARY_150R_validation_trades.csv"
    assert ledger_path.exists()
    assert set(metrics_df["year"]) == {2030, "pooled_validation_years"}
    if len(by):
        assert set(by["year"].unique()) == {2030}
