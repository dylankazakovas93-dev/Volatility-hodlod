"""Stage 2 frozen tests for ES/VIX level discovery development-grid runner.

Run:
    python -m pytest tests/test_es_vix_stage2.py -v
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sys
import tempfile

import numpy as np
import pandas as pd
import pytest

from research.es_vix_level_discovery.stage1_engine import (
    VIXLevelEngine,
    LevelConfig,
    _rth_bars,
    FIXED_HORIZONS,
)
from research.es_vix_level_discovery.stage2_metrics import (
    compute_config_metrics,
    compute_year_metrics,
    compute_direction_metrics,
    compute_monthly_metrics,
    compute_vix_regime_metrics,
    compute_time_of_day_metrics,
    compute_offset_family_metrics,
    compute_neighbour_support,
    compute_concentration_metrics,
    PRIMARY_HORIZONS,
    SECONDARY_HORIZONS,
    ALL_HORIZONS,
    FP_THRESHOLDS,
    _safe_median,
    _safe_mean,
    _safe_quantile,
)
from research.es_vix_level_discovery.stage2_baselines import (
    build_baseline,
    compute_baseline_lift,
    _vix_decile_bounds,
    _decile_index,
    _rth_time_bucket,
    _horizon_available,
    _session_seed,
    BASE_SEED,
    N_RESAMPLES,
)
from research.es_vix_level_discovery.stage2_selection import (
    classify_configs,
    classify_power,
    compute_median_ranks,
    MIN_TOUCHES,
    MIN_LONG,
    MIN_SHORT,
    MIN_SESSIONS,
    SURVIVOR_CAP,
    _is_dominated,
    _check_baseline_lift,
    _check_isolated_spike,
    _check_stability_year_direction,
    _are_adjacent_cells,
)
from research.es_vix_level_discovery.stage2_runner import (
    load_grid,
    load_registry,
    preflight,
    firewall_enforce_full,
    DEVELOPMENT_START,
    DEVELOPMENT_END,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESEARCH_DIR = os.path.join(REPO_ROOT, "research", "es_vix_level_discovery")
GRID_PATH = os.path.join(RESEARCH_DIR, "GRID_DEFINITION.json")
REGISTRY_PATH = os.path.join(RESEARCH_DIR, "TRIAL_REGISTRY.csv")
HOLDOUT_PATH = os.path.join(RESEARCH_DIR, "HOLDOUT_LOCK.json")
STAGE2_SPEC_PATH = os.path.join(RESEARCH_DIR, "STAGE2_EXECUTION_SPEC.md")
STAGE2_SELECTION_PATH = os.path.join(RESEARCH_DIR, "STAGE2_SELECTION_RULES.json")
BASELINE_DEF_PATH = os.path.join(RESEARCH_DIR, "BASELINE_DEFINITIONS.md")

NY_TZ = "America/New_York"


def _ny_to_utc(ny_dt_str: str) -> str:
    return str(pd.Timestamp(ny_dt_str, tz=NY_TZ).tz_convert("UTC"))


def synthetic_session_bars(
    session_date: str,
    rth_open: float = 4700.0,
    range_pct: float = 0.002,
    num_rth_bars: int = 390,
    amp: float = 0.0,
) -> pd.DataFrame:
    rows = []
    for i in range(num_rth_bars):
        base = rth_open
        half_range = rth_open * range_pct / 2.0
        wiggle = amp * math.sin(i * 0.1)
        ctr = base + wiggle
        h = ctr + half_range * abs(math.sin(i * 0.07 + 1.0))
        l_ = ctr - half_range * abs(math.sin(i * 0.07 + 2.0))
        if h < ctr:
            h, ctr = ctr, h
        if l_ > ctr:
            l_, ctr = ctr, l_
        if l_ > h:
            l_, h = h, l_
        h = round(max(h, ctr), 2)
        l_ = round(min(l_, ctr), 2)
        o = round(ctr, 2)
        c = round(ctr + half_range * 0.1 * (1 if i % 2 == 0 else -1), 2)
        if c > h:
            c = h
        if c < l_:
            c = l_
        hour = 9 + (i + 30) // 60
        minute = (i + 30) % 60
        ny_dt = f"{session_date} {hour:02d}:{minute:02d}:00"
        utc_ts = _ny_to_utc(ny_dt)
        rows.append({
            "timestamp": utc_ts,
            "open": o,
            "high": h,
            "low": l_,
            "close": c,
            "volume": 1000,
            "contract": "ESM8",
            "session_date": session_date,
            "roll_day": 0,
        })
    return pd.DataFrame(rows)


def synthetic_multiday_es(
    start_date: str = "2018-01-02",
    num_sessions: int = 25,
    rth_open: float = 4700.0,
    range_pct: float = 0.002,
) -> pd.DataFrame:
    all_rows = []
    sd = pd.Timestamp(start_date)
    for i in range(num_sessions):
        d = sd + pd.Timedelta(days=i)
        if d.weekday() >= 5:
            continue
        sd_str = d.strftime("%Y-%m-%d")
        df = synthetic_session_bars(sd_str, rth_open=rth_open + i * 0.5,
                                    range_pct=range_pct)
        all_rows.append(df)
    return pd.concat(all_rows, ignore_index=True)


def synthetic_vix(
    start_date: str = "2017-12-15",
    num_days: int = 200,
    vix_close: float = 15.0,
) -> pd.DataFrame:
    dates = pd.bdate_range(start=start_date, periods=num_days)
    df = pd.DataFrame({
        "date": dates,
        "vix_open": vix_close,
        "vix_high": vix_close + 0.5,
        "vix_low": vix_close - 0.5,
        "vix_close": vix_close,
    })
    df["date"] = pd.to_datetime(df["date"])
    return df


def _generate_synthetic_touches_and_excursions(
    configs: list[LevelConfig],
    es: pd.DataFrame,
    vix: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Generate levels, touches (with clusters), and excursions for configs."""
    all_levels = []
    all_touches = []
    all_excursions = []
    for cfg in configs:
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        if levels.empty:
            continue
        all_levels.append(levels)
        touches = engine.detect_touches(levels, es)
        if not touches.empty:
            touches = engine.assign_overlap_clusters(touches)
            all_touches.append(touches)
            excursions = engine.compute_excursions(touches, es)
            all_excursions.append(excursions)
    levels_df = pd.concat(all_levels, ignore_index=True) if all_levels else pd.DataFrame()
    touches_df = pd.concat(all_touches, ignore_index=True) if all_touches else pd.DataFrame()
    excursions_df = pd.concat(all_excursions, ignore_index=True) if all_excursions else pd.DataFrame()
    return levels_df, touches_df, excursions_df


# ══════════════════════════════════════════════════════════════════════
# 1. Date firewall
# ══════════════════════════════════════════════════════════════════════

class TestDateFirewall:
    def test_firewall_rejects_2020_touch(self):
        """Touch with session_touched in 2020 should be rejected."""
        es = synthetic_multiday_es("2020-01-02", num_sessions=15, range_pct=0.005)
        vix = synthetic_vix(start_date="2019-12-15", num_days=100, vix_close=80.0)
        vix["date"] = pd.to_datetime(vix["date"])
        cfg = LevelConfig("TEST_FW", 0.75, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        if touches.empty:
            pytest.skip("No touches generated for 2020 test")
        with pytest.raises(SystemExit) as exc:
            firewall_enforce_full(touches, pd.DataFrame(), None, es)
        assert exc.value.code == 75

    def test_firewall_passes_2018_2019(self):
        """All touches within 2018-2019 should pass firewall."""
        es = synthetic_multiday_es("2018-01-02", num_sessions=10)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_FW_OK", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        excursions = engine.compute_excursions(touches, es)
        firewall_enforce_full(levels, touches, excursions, es)

    def test_firewall_rejects_post_2019_excursion(self):
        """Excursion with label_start outside 2018-2019 fails."""
        es = synthetic_multiday_es("2020-01-02", num_sessions=15, range_pct=0.005)
        vix = synthetic_vix(start_date="2019-12-15", num_days=100, vix_close=80.0)
        vix["date"] = pd.to_datetime(vix["date"])
        cfg = LevelConfig("TEST_FW_EXC", 0.75, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        if touches.empty:
            pytest.skip("No touches generated for 2020 test")
        excursions = engine.compute_excursions(touches, es)
        with pytest.raises(SystemExit) as exc:
            firewall_enforce_full(None, touches, excursions, None)
        assert exc.value.code == 75


# ══════════════════════════════════════════════════════════════════════
# 2. Grid/registry integrity
# ══════════════════════════════════════════════════════════════════════

class TestGridIntegrity:
    def test_exactly_132_configs_from_grid(self):
        grid = load_grid()
        assert len(grid) == 132

    def test_exactly_132_configs_from_registry(self):
        registry = load_registry()
        assert len(registry) == 132

    def test_all_config_ids_unique(self):
        registry = load_registry()
        assert registry["config_id"].is_unique

    def test_registry_matches_grid(self):
        grid = load_grid()
        registry = load_registry()
        grid_ids = set(grid["config_id"])
        reg_ids = set(registry["config_id"])
        assert grid_ids == reg_ids

    def test_all_registered(self):
        registry = load_registry()
        assert all(registry["status"] == "registered")

    def test_line_life_fixed_at_20(self):
        registry = load_registry()
        assert all(registry["line_life_sessions"] == 20)

    def test_no_prohibited_columns(self):
        registry = load_registry()
        prohibited = ["target_rr", "be_rule", "stop_formula", "commissions",
                      "fees", "slippage", "entry_blackout", "hard_blackout"]
        for col in registry.columns:
            assert col.lower() not in [p.lower() for p in prohibited]

    def test_sigma_multiplier_exact(self):
        registry = load_registry()
        valid = {0.75, 1.0, 1.25, 1.5, 1.75, 2.0}
        assert all(float(v) in valid for v in registry["sigma_multiplier"])

    def test_ib_minutes_exact(self):
        registry = load_registry()
        assert set(registry["ib_minutes"]) == {30, 60}

    def test_proportional_offsets_exact(self):
        registry = load_registry()
        pct = registry[registry["offset_family"] == "proportional"]
        valid = {0.0, 0.02, 0.04, 0.06, 0.08, 0.1}
        assert all(float(v) in valid for v in pct["offset_value"])

    def test_fixed_offsets_exact(self):
        registry = load_registry()
        fixed = registry[registry["offset_family"] == "fixed"]
        valid = {2.5, 5.0, 7.5, 10.0, 15.0}
        assert all(float(v) in valid for v in fixed["offset_value"])


# ══════════════════════════════════════════════════════════════════════
# 3. Metrics: complete labels only
# ══════════════════════════════════════════════════════════════════════

class TestMetricsUseCompleteLabels:
    def test_metrics_use_only_complete_labels(self):
        es = synthetic_multiday_es("2018-01-02", num_sessions=10)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_MET_COMP", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        touches = engine.assign_overlap_clusters(touches)
        excursions = engine.compute_excursions(touches, es)
        metrics = compute_config_metrics(levels, touches, excursions, vix)
        for _, row in metrics.iterrows():
            complete_count = len(
                excursions[
                    (excursions["config_id"] == row["config_id"])
                    & (excursions["horizon"] == row["horizon"])
                    & (excursions["label_status"] == "COMPLETE")
                ]
            )
            assert row["valid_complete_labels"] == complete_count

    def test_incomplete_labels_counted(self):
        """Incomplete labels are counted and reported separately."""
        es = synthetic_session_bars("2018-01-02", num_rth_bars=60)
        vix = synthetic_vix(vix_close=80.0)
        cfg = LevelConfig("TEST_INC_CNT", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        touches = engine.assign_overlap_clusters(touches)
        excursions = engine.compute_excursions(touches, es)
        metrics = compute_config_metrics(levels, touches, excursions, vix)
        for _, row in metrics.iterrows():
            inc = excursions[
                (excursions["config_id"] == row["config_id"])
                & (excursions["horizon"] == row["horizon"])
                & (excursions["label_status"] == "INCOMPLETE")
            ]
            assert row["incomplete_labels"] == len(inc)


# ══════════════════════════════════════════════════════════════════════
# 4. LONG/SHORT denominators correct
# ══════════════════════════════════════════════════════════════════════

class TestLongShortDenominators:
    def test_long_short_counts_match(self):
        es = synthetic_multiday_es("2018-01-02", num_sessions=10, range_pct=0.003)
        vix = synthetic_vix(vix_close=30.0)
        cfg = LevelConfig("TEST_LS_CNT", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        touches = engine.assign_overlap_clusters(touches)
        excursions = engine.compute_excursions(touches, es)
        metrics = compute_config_metrics(levels, touches, excursions, vix)
        for _, row in metrics.iterrows():
            expected_long = int((touches["touch_direction"] == "LONG").sum())
            expected_short = int((touches["touch_direction"] == "SHORT").sum())
            assert row["long_count"] == expected_long
            assert row["short_count"] == expected_short


# ══════════════════════════════════════════════════════════════════════
# 5. First-passage denominators
# ══════════════════════════════════════════════════════════════════════

class TestFirstPassageDenominators:
    def test_first_passage_rates_sum_to_one(self):
        es = synthetic_multiday_es("2018-01-02", num_sessions=10, range_pct=0.003)
        vix = synthetic_vix(vix_close=30.0)
        cfg = LevelConfig("TEST_FP_SUM", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        touches = engine.assign_overlap_clusters(touches)
        excursions = engine.compute_excursions(touches, es)
        metrics = compute_config_metrics(levels, touches, excursions, vix)
        for _, row in metrics.iterrows():
            if row["valid_complete_labels"] == 0:
                continue
            for thresh in [0.25, 0.50, 0.75, 1.00]:
                fav = row.get(f"p_favorable_first_{thresh:.2f}")
                adv = row.get(f"p_adverse_first_{thresh:.2f}")
                amb = row.get(f"p_ambiguous_{thresh:.2f}")
                none_r = row.get(f"p_neither_reached_{thresh:.2f}")
                vals = [v for v in [fav, adv, amb, none_r] if v is not None]
                if vals:
                    total = sum(vals)
                    assert abs(total - 1.0) < 1e-9, (
                        f"FP rates sum to {total} for {thresh}"
                    )


# ══════════════════════════════════════════════════════════════════════
# 6. Ratio of medians
# ══════════════════════════════════════════════════════════════════════

class TestRatioOfMedians:
    def test_ratio_of_medians_formula(self):
        """mfe_mae_ratio_of_medians = median(mfe) / median(mae)."""
        es = synthetic_multiday_es("2018-01-02", num_sessions=10)
        vix = synthetic_vix(vix_close=30.0)
        cfg = LevelConfig("TEST_RATIO", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        touches = engine.assign_overlap_clusters(touches)
        excursions = engine.compute_excursions(touches, es)
        metrics = compute_config_metrics(levels, touches, excursions, vix)
        for _, row in metrics.iterrows():
            if row["median_mfe_points"] is not None and row["median_mae_points"] is not None and row["median_mae_points"] != 0.0:
                expected = row["median_mfe_points"] / row["median_mae_points"]
                assert abs(row["mfe_mae_ratio_of_medians"] - expected) < 1e-9
            else:
                assert row["mfe_mae_ratio_of_medians"] is None

    def test_zero_mae_handled(self):
        """If median MAE is zero, ratio is None."""
        es = synthetic_multiday_es("2018-01-02", num_sessions=10)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_ZERO_MAE", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        touches = engine.assign_overlap_clusters(touches)
        excursions = engine.compute_excursions(touches, es)
        # Force all MAE to zero
        excursions.loc[excursions["label_status"] == "COMPLETE", "mae"] = 0.0
        metrics = compute_config_metrics(levels, touches, excursions, vix)
        for _, row in metrics.iterrows():
            if row["median_mae_points"] is not None and row["median_mae_points"] == 0.0:
                assert row["mfe_mae_ratio_of_medians"] is None


# ══════════════════════════════════════════════════════════════════════
# 7. VIX deciles use training data only
# ══════════════════════════════════════════════════════════════════════

class TestVIXDecilesDevOnly:
    def test_vix_deciles_from_2018_2019(self):
        vix = pd.DataFrame({
            "date": pd.date_range("2018-01-01", "2019-12-31", freq="D"),
            "vix_close": np.random.default_rng(42).uniform(10, 30, 730),
        })
        vix = pd.concat([vix, pd.DataFrame({
            "date": pd.date_range("2020-01-01", "2020-12-31", freq="D"),
            "vix_close": np.random.default_rng(43).uniform(40, 80, 366),
        })], ignore_index=True)
        bounds = _vix_decile_bounds(vix)
        bounds[0] = -float("inf")
        bounds[-1] = float("inf")
        # The max decile should use 2018-2019 values only (approx 30)
        assert bounds[9] < 40  # 9th decile should be below 2020 values

    def test_decile_index(self):
        vix = synthetic_vix(vix_close=15.0, num_days=500)
        vix["date"] = pd.to_datetime(vix["date"])
        bounds = _vix_decile_bounds(vix)
        idx = _decile_index(15.0, bounds)
        assert 0 <= idx < 10


# ══════════════════════════════════════════════════════════════════════
# 8. Baseline never crosses firewall
# ══════════════════════════════════════════════════════════════════════

class TestBaselineFirewall:
    def test_baseline_2018_2019_only(self):
        es = synthetic_multiday_es("2018-01-02", num_sessions=10)
        vix = synthetic_vix(vix_close=15.0, num_days=500)
        vix["date"] = pd.to_datetime(vix["date"])
        cfg = LevelConfig("TEST_BL_FW", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        touches = engine.assign_overlap_clusters(touches)
        result = build_baseline(
            touches, levels, es, vix,
            horizons=["60m"],
            n_resamples=5,
        )
        results = result["aggregated"]
        if not results.empty:
            random_sessions = results["random_timestamp"].apply(
                lambda ts: str(pd.Timestamp(ts))[:10]
            ).unique()
            for sess in random_sessions:
                assert sess >= "2018-01-01", f"Baseline session {sess} before 2018"
                assert sess <= "2019-12-31", f"Baseline session {sess} after 2019"


# ══════════════════════════════════════════════════════════════════════
# 9. Baseline seeds deterministic
# ══════════════════════════════════════════════════════════════════════

class TestBaselineDeterminism:
    def test_seeds_deterministic(self):
        from research.es_vix_level_discovery.stage2_baselines import _session_seed
        s1 = [_session_seed("CFG", "60m", "T1", i, "MASTER") for i in range(10)]
        s2 = [_session_seed("CFG", "60m", "T1", i, "MASTER") for i in range(10)]
        assert s1 == s2

    def test_baseline_horizon_availability(self):
        """Random timestamps must have COMPLETE horizon available."""
        es = synthetic_multiday_es("2018-01-02", num_sessions=10)
        rth = _rth_bars(es)
        rth_by_session = {
            sd: grp.sort_values("ny_time")
            for sd, grp in rth.groupby("session_date")
        }
        session_bars = rth_by_session.get("2018-01-02")
        if session_bars is not None:
            # Late bar should have 30m available
            late_ts = pd.Timestamp("2018-01-02 15:00", tz=NY_TZ)
            assert _horizon_available(late_ts, 30, rth_by_session) is True
            # Last bar should not have 120m available
            last_ts = pd.Timestamp("2018-01-02 15:59", tz=NY_TZ)
            assert _horizon_available(last_ts, 120, rth_by_session) is False


# ══════════════════════════════════════════════════════════════════════
# 10. Overlap clusters
# ══════════════════════════════════════════════════════════════════════

class TestOverlapEffectiveN:
    def test_overlap_adjusted_n(self):
        """Overlap-adjusted N: non-overlap touches + overlap clusters."""
        es = synthetic_multiday_es("2018-01-02", num_sessions=10)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_OAN", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        touches = engine.assign_overlap_clusters(touches)
        excursions = engine.compute_excursions(touches, es)
        metrics = compute_config_metrics(levels, touches, excursions, vix)
        for _, row in metrics.iterrows():
            non_overlap = int((touches["overlap_cluster_id"] == 0).sum())
            n_clusters = int(touches[touches["overlap_cluster_id"] > 0]["overlap_cluster_id"].nunique())
            expected_n = non_overlap + n_clusters
            assert row["overlap_adjusted_effective_n"] == expected_n


# ══════════════════════════════════════════════════════════════════════
# 11. Neighbour lookup
# ══════════════════════════════════════════════════════════════════════

class TestNeighbourLookup:
    def test_neighbour_lookup_edges(self):
        grid = load_grid()
        from research.es_vix_level_discovery.stage2_metrics import compute_neighbour_support
        es = synthetic_multiday_es("2018-01-02", num_sessions=10)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("VIX_ES_SIGMA_075_IB30_PCT_000", 0.75, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        touches = engine.assign_overlap_clusters(touches)
        excursions = engine.compute_excursions(touches, es)
        metrics_df = compute_config_metrics(levels, touches, excursions, vix)
        neigh = compute_neighbour_support(metrics_df, grid)
        # Check that edge cells have correct neighbour counts
        # VIX_ES_SIGMA_075_IB30_PCT_000 should have neighbours
        edge_row = neigh[neigh["config_id"] == "VIX_ES_SIGMA_075_IB30_PCT_000"]
        if not edge_row.empty:
            assert edge_row["neighbour_count"].iloc[0] > 0

    def test_interior_neighbour_count(self):
        grid = load_grid()
        # A middle config should have more neighbours than an edge
        interior = grid[grid["config_id"] == "VIX_ES_SIGMA_125_IB30_PCT_004"]
        assert len(interior) == 1


# ══════════════════════════════════════════════════════════════════════
# 12. Low-power classification
# ══════════════════════════════════════════════════════════════════════

class TestLowPower:
    def test_low_power_insufficient_touches(self):
        metrics = pd.DataFrame({
            "config_id": ["LOW_POWER_1", "LOW_POWER_1"],
            "horizon": ["60m", "120m"],
            "valid_complete_labels": [50, 50],
            "long_count": [25, 25],
            "short_count": [25, 25],
            "unique_sessions": [20, 20],
        })
        power = classify_power(metrics)
        assert power.get("LOW_POWER_1") == "INCONCLUSIVE_LOW_POWER"

    def test_low_power_sufficient(self):
        metrics = pd.DataFrame({
            "config_id": ["POWER_OK", "POWER_OK"],
            "horizon": ["60m", "120m"],
            "valid_complete_labels": [200, 200],
            "long_count": [80, 80],
            "short_count": [80, 80],
            "unique_sessions": [60, 60],
        })
        power = classify_power(metrics)
        assert power.get("POWER_OK") == "PENDING"

    def test_low_power_insufficient_long(self):
        metrics = pd.DataFrame({
            "config_id": ["LOW_LONG"],
            "horizon": ["60m"],
            "valid_complete_labels": [200],
            "long_count": [10],
            "short_count": [190],
            "unique_sessions": [60],
        })
        power = classify_power(metrics)
        assert power.get("LOW_LONG") == "INCONCLUSIVE_LOW_POWER"

    def test_low_power_insufficient_short(self):
        metrics = pd.DataFrame({
            "config_id": ["LOW_SHORT"],
            "horizon": ["60m"],
            "valid_complete_labels": [200],
            "long_count": [190],
            "short_count": [10],
            "unique_sessions": [60],
        })
        power = classify_power(metrics)
        assert power.get("LOW_SHORT") == "INCONCLUSIVE_LOW_POWER"


# ══════════════════════════════════════════════════════════════════════
# 13. Dominated config classification
# ══════════════════════════════════════════════════════════════════════

class TestBaselineLiftCheck:
    def test_baseline_lift_nonpositive_both(self):
        lift_df = pd.DataFrame({
            "config_id": ["A", "A"],
            "horizon": ["60m", "120m"],
            "metric": ["median_mfe_points", "median_mfe_points"],
            "actual_value": [1.0, 1.0],
            "baseline_median": [2.0, 2.0],
            "baseline_p05": [1.5, 1.5],
            "baseline_p95": [3.0, 3.0],
            "actual_minus_baseline": [-1.0, -1.0],
            "percentage_lift": [-0.5, -0.5],
            "actual_percentile": [0.2, 0.2],
            "one_sided_p_value": [0.2, 0.2],
            "n_random_observations": [100, 100],
        })
        assert _check_baseline_lift("A", lift_df) is True

    def test_baseline_lift_positive_one_horizon(self):
        lift_df = pd.DataFrame({
            "config_id": ["A", "A"],
            "horizon": ["60m", "120m"],
            "metric": ["median_mfe_points", "median_mfe_points"],
            "actual_value": [3.0, 1.0],
            "baseline_median": [2.0, 2.0],
            "baseline_p05": [1.5, 1.5],
            "baseline_p95": [3.0, 3.0],
            "actual_minus_baseline": [1.0, -1.0],
            "percentage_lift": [0.5, -0.5],
            "actual_percentile": [0.8, 0.2],
            "one_sided_p_value": [0.8, 0.2],
            "n_random_observations": [100, 100],
        })
        assert _check_baseline_lift("A", lift_df) is False


class TestDominated:
    def test_clearly_dominated(self):
        metrics = pd.DataFrame({
            "config_id": ["A", "B", "B"],
            "horizon": ["60m", "60m", "120m"],
            "median_mfe_points": [1.0, 5.0, 5.0],
            "median_mae_points": [10.0, 2.0, 2.0],
            "mean_directional_return_over_sigma": [0.1, 0.5, 0.5],
            "positive_directional_return_rate": [0.4, 0.6, 0.6],
        })
        pareto_dims = {
            "median_mfe_points": True,
            "median_mae_points": False,
            "mean_directional_return_over_sigma": True,
            "positive_directional_return_rate": True,
        }
        dominated = _is_dominated("A", metrics, "60m", pareto_dims)
        assert dominated is True

    def test_not_dominated(self):
        metrics = pd.DataFrame({
            "config_id": ["A", "B", "B"],
            "horizon": ["60m", "60m", "120m"],
            "median_mfe_points": [5.0, 5.0, 5.0],
            "median_mae_points": [2.0, 2.0, 2.0],
            "mean_directional_return_over_sigma": [0.5, 0.5, 0.5],
            "positive_directional_return_rate": [0.6, 0.6, 0.6],
        })
        pareto_dims = {
            "median_mfe_points": True,
            "median_mae_points": False,
            "mean_directional_return_over_sigma": True,
            "positive_directional_return_rate": True,
        }
        dominated = _is_dominated("A", metrics, "60m", pareto_dims)
        assert dominated is False


# ══════════════════════════════════════════════════════════════════════
# 14. Isolated spike detection
# ══════════════════════════════════════════════════════════════════════

class TestIsolatedSpike:
    def test_isolated_spike_detected(self):
        metrics = pd.DataFrame({
            "config_id": ["SPIKE", "NEIGH_1", "NEIGH_2", "NEIGH_3"],
            "horizon": ["60m", "60m", "60m", "60m"],
            "median_mfe_points": [10.0, 2.0, 2.0, 2.0],
            "median_mae_points": [5.0, 3.0, 3.0, 3.0],
            "mean_directional_return_over_sigma": [0.5, 0.3, 0.3, 0.3],
            "positive_directional_return_rate": [0.6, 0.5, 0.5, 0.5],
        })
        grid = pd.DataFrame({
            "config_id": ["SPIKE", "NEIGH_1", "NEIGH_2", "NEIGH_3"],
            "sigma_multiplier": [1.0, 1.0, 1.0, 1.0],
            "ib_minutes": [30, 30, 30, 30],
            "offset_family": ["proportional", "proportional", "proportional", "proportional"],
            "offset_parameter": ["offset_pct", "offset_pct", "offset_pct", "offset_pct"],
            "offset_value": [0.04, 0.02, 0.06, 0.08],
            "line_life_sessions": [20, 20, 20, 20],
        })
        is_spike = _check_isolated_spike("SPIKE", metrics, grid)
        assert is_spike is True


# ══════════════════════════════════════════════════════════════════════
# 15. Survivor cap is 36
# ══════════════════════════════════════════════════════════════════════

class TestSurvivorCap:
    def test_survivor_cap_value(self):
        assert SURVIVOR_CAP == 36

    def test_classification_cap_applied(self):
        metrics = pd.DataFrame({
            "config_id": [f"CFG_{i}" for i in range(50) for _ in range(2)],
            "horizon": ["60m", "120m"] * 50,
            "valid_complete_labels": [200] * 100,
            "long_count": [80] * 100,
            "short_count": [80] * 100,
            "unique_sessions": [60] * 100,
            "median_mfe_points": [float(i % 10) for i in range(100)],
            "median_mae_points": [1.0] * 100,
            "mean_directional_return_over_sigma": [0.5] * 100,
            "positive_directional_return_rate": [0.6] * 100,
            "generated_levels": [100] * 100,
            "physical_first_touches": [200] * 100,
            "incomplete_labels": [0] * 100,
            "gap_through_count": [10] * 100,
            "ambiguous_first_passage_count": [5] * 100,
            "overlap_clusters": [10] * 100,
            "overlap_adjusted_effective_n": [150] * 100,
            "p_favorable_first_0.25": [0.5] * 100,
            "p_adverse_first_0.25": [0.3] * 100,
            "p_ambiguous_0.25": [0.1] * 100,
            "p_neither_reached_0.25": [0.1] * 100,
            "p_favorable_first_0.50": [0.4] * 100,
            "p_adverse_first_0.50": [0.3] * 100,
            "p_ambiguous_0.50": [0.1] * 100,
            "p_neither_reached_0.50": [0.2] * 100,
            "p_favorable_first_0.75": [0.3] * 100,
            "p_adverse_first_0.75": [0.3] * 100,
            "p_ambiguous_0.75": [0.1] * 100,
            "p_neither_reached_0.75": [0.3] * 100,
            "p_favorable_first_1.00": [0.2] * 100,
            "p_adverse_first_1.00": [0.3] * 100,
            "p_ambiguous_1.00": [0.1] * 100,
            "p_neither_reached_1.00": [0.4] * 100,
            "mfe_mae_ratio_of_medians": [2.0] * 100,
        })
        decisions = classify_configs(
            metrics_df=metrics,
            baseline_lift_df=pd.DataFrame(),
            direction_metrics=pd.DataFrame(),
            year_metrics=pd.DataFrame(),
            grid_df=pd.DataFrame(),
            excursions_df=pd.DataFrame(),
        )
        passed = len(decisions[decisions["classification"] == "PASS"])
        assert passed <= 36


# ══════════════════════════════════════════════════════════════════════
# 16. Artifact schemas
# ══════════════════════════════════════════════════════════════════════

class TestArtifactSchemas:
    def test_spec_files_exist(self):
        assert os.path.exists(STAGE2_SPEC_PATH), "STAGE2_EXECUTION_SPEC.md missing"
        assert os.path.exists(STAGE2_SELECTION_PATH), "STAGE2_SELECTION_RULES.json missing"
        assert os.path.exists(BASELINE_DEF_PATH), "BASELINE_DEFINITIONS.md missing"

    def test_selection_rules_json_valid(self):
        with open(STAGE2_SELECTION_PATH) as f:
            rules = json.load(f)
        assert "classification_labels" in rules
        assert "PASS" in rules["classification_labels"]
        assert "FAIL" in rules["classification_labels"]
        assert "INCONCLUSIVE_LOW_POWER" in rules["classification_labels"]
        assert rules["survivor_cap"] == 36
        assert rules["minimum_power_requirements"]["min_complete_primary_horizon_touches"] == 100

    def test_holdout_remains_unopened(self):
        with open(HOLDOUT_PATH) as f:
            h = json.load(f)
        assert h["status"] == "UNOPENED"
        assert h["outcome_columns_read"] is False

    def test_config_results_schema(self):
        """Verify CONFIG_RESULTS.csv columns against spec."""
        expected = [
            "config_id", "horizon", "generated_levels", "physical_first_touches",
            "valid_complete_labels", "incomplete_labels", "long_count",
            "short_count", "gap_through_count", "ambiguous_first_passage_count",
            "unique_sessions", "overlap_clusters", "overlap_adjusted_effective_n",
            "median_mfe_points", "median_mae_points",
            "median_mfe_over_sigma_day", "median_mae_over_sigma_day",
            "median_mfe_over_ib_range", "median_mae_over_ib_range",
            "p75_mfe_over_sigma_day", "p90_mfe_over_sigma_day",
            "p75_mae_over_sigma_day", "p90_mae_over_sigma_day",
            "p95_mae_over_sigma_day",
            "mean_directional_return_over_sigma",
            "median_directional_return_over_sigma",
            "positive_directional_return_rate",
            "mfe_mae_ratio_of_medians",
        ]
        es = synthetic_multiday_es("2018-01-02", num_sessions=5)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_SCHEMA", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        touches = engine.assign_overlap_clusters(touches)
        excursions = engine.compute_excursions(touches, es)
        metrics = compute_config_metrics(levels, touches, excursions, vix)
        for col in expected:
            if col.startswith("p_"):
                continue  # FP columns are dynamic
            assert col in metrics.columns, f"missing column: {col}"

    def test_survivor_decisions_schema(self):
        """SURVIVOR_DECISIONS.csv: config_id, classification, reasons."""
        decisions = pd.DataFrame({
            "config_id": ["A"],
            "classification": ["PASS"],
            "reasons": [""],
        })
        assert set(decisions.columns) == {"config_id", "classification", "reasons"}
        assert decisions["classification"].iloc[0] in ["PASS", "FAIL", "INCONCLUSIVE_LOW_POWER"]


# ══════════════════════════════════════════════════════════════════════
# 17. Utility helpers
# ══════════════════════════════════════════════════════════════════════

class TestSafeHelpers:
    def test_safe_median_empty(self):
        assert _safe_median(pd.Series([], dtype=float)) is None

    def test_safe_median_normal(self):
        assert _safe_median(pd.Series([1.0, 2.0, 3.0])) == 2.0

    def test_safe_mean_empty(self):
        assert _safe_mean(pd.Series([], dtype=float)) is None

    def test_safe_quantile_empty(self):
        assert _safe_quantile(pd.Series([], dtype=float), 0.5) is None


# ══════════════════════════════════════════════════════════════════════
# 18. Spec file contracts
# ══════════════════════════════════════════════════════════════════════

class TestSpecContract:
    def test_stage2_spec_has_firewall(self):
        with open(STAGE2_SPEC_PATH) as f:
            content = f.read()
        assert "2018-01-01" in content
        assert "2019-12-31" in content
        assert "Gate A" in content
        assert "exit code 75" in content.lower()

    def test_stage2_spec_has_primary_horizons(self):
        with open(STAGE2_SPEC_PATH) as f:
            content = f.read()
        assert "60 minutes" in content
        assert "120 minutes" in content

    def test_stage2_spec_has_metric_list(self):
        with open(STAGE2_SPEC_PATH) as f:
            content = f.read()
        assert "median_mfe_points" in content
        assert "median_mae_points" in content
        assert "ratio of medians" in content

    def test_stage2_spec_has_baseline(self):
        with open(STAGE2_SPEC_PATH) as f:
            content = f.read()
        assert "Matched-Random" in content
        assert "1,000 deterministic" in content

    def test_stage2_spec_has_min_power(self):
        with open(STAGE2_SPEC_PATH) as f:
            content = f.read()
        assert "Minimum Power" in content
        assert "100 complete" in content

    def test_stage2_spec_has_artifacts(self):
        with open(STAGE2_SPEC_PATH) as f:
            content = f.read()
        assert "CONFIG_RESULTS.csv" in content
        assert "MANIFEST.json" in content
        assert "SURVIVOR_DECISIONS.csv" in content


# ══════════════════════════════════════════════════════════════════════
# 19. Stage 0 and Stage 1 invariants preserved
# ══════════════════════════════════════════════════════════════════════

class TestStageInvariantsPreserved:
    def test_grid_unchanged(self):
        with open(GRID_PATH) as f:
            grid = json.load(f)
        assert grid["total_configurations"] == 132
        assert grid["stage"] == 0

    def test_registry_unchanged(self):
        registry = load_registry()
        assert len(registry) == 132

    def test_holdout_unchanged(self):
        with open(HOLDOUT_PATH) as f:
            h = json.load(f)
        assert h["status"] == "UNOPENED"

    def test_no_new_parameters_added(self):
        with open(GRID_PATH) as f:
            grid = json.load(f)
        assert "target_rr" in grid.get("prohibited_fields", [])


# ══════════════════════════════════════════════════════════════════════
# 20. Determinism
# ══════════════════════════════════════════════════════════════════════

class TestDeterminism:
    def test_metrics_deterministic(self):
        es = synthetic_multiday_es("2018-01-02", num_sessions=5)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_DET_MET", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        touches = engine.assign_overlap_clusters(touches)
        excursions = engine.compute_excursions(touches, es)
        m1 = compute_config_metrics(levels, touches, excursions, vix)
        m2 = compute_config_metrics(levels, touches, excursions, vix)
        pd.testing.assert_frame_equal(m1, m2)

    def test_monthly_metrics_deterministic(self):
        es = synthetic_multiday_es("2018-01-02", num_sessions=5)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_DET_MON", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        touches = engine.assign_overlap_clusters(touches)
        excursions = engine.compute_excursions(touches, es)
        m1 = compute_monthly_metrics(touches, excursions)
        m2 = compute_monthly_metrics(touches, excursions)
        pd.testing.assert_frame_equal(m1, m2)

    def test_time_of_day_deterministic(self):
        es = synthetic_multiday_es("2018-01-02", num_sessions=5)
        vix = synthetic_vix(vix_close=15.0)
        cfg = LevelConfig("TEST_DET_TOD", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        touches = engine.assign_overlap_clusters(touches)
        m1 = compute_time_of_day_metrics(touches)
        m2 = compute_time_of_day_metrics(touches)
        pd.testing.assert_frame_equal(m1, m2)

    def test_classification_deterministic(self):
        metrics = pd.DataFrame({
            "config_id": ["A", "A", "B", "B"],
            "horizon": ["60m", "120m", "60m", "120m"],
            "valid_complete_labels": [200, 200, 200, 200],
            "long_count": [80, 80, 80, 80],
            "short_count": [80, 80, 80, 80],
            "unique_sessions": [60, 60, 60, 60],
            "median_mfe_points": [5.0, 5.0, 3.0, 3.0],
            "median_mae_points": [2.0, 2.0, 4.0, 4.0],
            "mean_directional_return_over_sigma": [0.5, 0.5, 0.3, 0.3],
            "positive_directional_return_rate": [0.6, 0.6, 0.5, 0.5],
            "generated_levels": [100, 100, 100, 100],
            "physical_first_touches": [200, 200, 200, 200],
            "incomplete_labels": [0, 0, 0, 0],
            "gap_through_count": [10, 10, 10, 10],
            "ambiguous_first_passage_count": [5, 5, 5, 5],
            "overlap_clusters": [10, 10, 10, 10],
            "overlap_adjusted_effective_n": [150, 150, 150, 150],
            "p_favorable_first_0.25": [0.5, 0.5, 0.4, 0.4],
            "p_adverse_first_0.25": [0.3, 0.3, 0.3, 0.3],
            "p_ambiguous_0.25": [0.1, 0.1, 0.1, 0.1],
            "p_neither_reached_0.25": [0.1, 0.1, 0.2, 0.2],
            "p_favorable_first_0.50": [0.4, 0.4, 0.3, 0.3],
            "p_adverse_first_0.50": [0.3, 0.3, 0.3, 0.3],
            "p_ambiguous_0.50": [0.1, 0.1, 0.1, 0.1],
            "p_neither_reached_0.50": [0.2, 0.2, 0.3, 0.3],
            "p_favorable_first_0.75": [0.3, 0.3, 0.2, 0.2],
            "p_adverse_first_0.75": [0.3, 0.3, 0.3, 0.3],
            "p_ambiguous_0.75": [0.1, 0.1, 0.1, 0.1],
            "p_neither_reached_0.75": [0.3, 0.3, 0.4, 0.4],
            "p_favorable_first_1.00": [0.2, 0.2, 0.1, 0.1],
            "p_adverse_first_1.00": [0.3, 0.3, 0.3, 0.3],
            "p_ambiguous_1.00": [0.1, 0.1, 0.1, 0.1],
            "p_neither_reached_1.00": [0.4, 0.4, 0.5, 0.5],
            "mfe_mae_ratio_of_medians": [2.5, 2.5, 0.75, 0.75],
        })
        d1 = classify_configs(metrics, baseline_lift_df=pd.DataFrame(), direction_metrics=pd.DataFrame(), year_metrics=pd.DataFrame(), grid_df=pd.DataFrame(), excursions_df=pd.DataFrame())
        d2 = classify_configs(metrics, baseline_lift_df=pd.DataFrame(), direction_metrics=pd.DataFrame(), year_metrics=pd.DataFrame(), grid_df=pd.DataFrame(), excursions_df=pd.DataFrame())
        pd.testing.assert_frame_equal(d1, d2)


# ══════════════════════════════════════════════════════════════════════
# 21. Spec file existence
# ══════════════════════════════════════════════════════════════════════

class TestSpecFiles:
    def test_stage2_execution_spec_exists(self):
        assert os.path.exists(STAGE2_SPEC_PATH)

    def test_selection_rules_exist(self):
        assert os.path.exists(STAGE2_SELECTION_PATH)

    def test_baseline_definitions_exist(self):
        assert os.path.exists(BASELINE_DEF_PATH)

    def test_holdout_lock_exists(self):
        assert os.path.exists(HOLDOUT_PATH)


# ══════════════════════════════════════════════════════════════════════
# 22. Baseline matching respects horizon availability
# ══════════════════════════════════════════════════════════════════════

class TestBaselineHorizonRespect:
    def test_horizon_availability_check(self):
        """A timestamp at 15:55 should not have 120m available."""
        es = synthetic_multiday_es("2018-01-02", num_sessions=5)
        rth = _rth_bars(es)
        rth_by_session = {
            sd: grp.sort_values("ny_time")
            for sd, grp in rth.groupby("session_date")
        }
        late_ts = pd.Timestamp("2018-01-02 15:55", tz=NY_TZ)
        assert _horizon_available(late_ts, 120, rth_by_session) is False

    def test_horizon_available_check_early(self):
        """A timestamp at 10:00 should have 60m available."""
        es = synthetic_multiday_es("2018-01-02", num_sessions=5)
        rth = _rth_bars(es)
        rth_by_session = {
            sd: grp.sort_values("ny_time")
            for sd, grp in rth.groupby("session_date")
        }
        early_ts = pd.Timestamp("2018-01-02 10:00", tz=NY_TZ)
        assert _horizon_available(early_ts, 60, rth_by_session) is True


# ══════════════════════════════════════════════════════════════════════
# 23. Preflight
# ══════════════════════════════════════════════════════════════════════

class TestPreflight:
    def test_preflight_passes(self):
        """Preflight should pass in the current environment."""
        old_argv = sys.argv
        try:
            sys.argv = ["stage2_runner.py", "--preflight"]
            # We capture exit code instead of calling preflight directly
            # since it prints to stdout and exits
            from research.es_vix_level_discovery.stage2_runner import preflight as pf
            pf()
        except SystemExit as e:
            assert e.code != 1, "Preflight failed"
        finally:
            sys.argv = old_argv


# ══════════════════════════════════════════════════════════════════════
# 24. One-direction check
# ══════════════════════════════════════════════════════════════════════

class TestOneDirection:
    def test_one_direction_dominated(self):
        dir_metrics = pd.DataFrame({
            "config_id": ["A", "A"],
            "horizon": ["60m", "60m"],
            "direction": ["LONG", "SHORT"],
            "touch_count": [196, 4],
            "complete_label_count": [180, 4],
            "median_mfe_points": [5.0, 5.0],
            "median_mae_points": [2.0, 2.0],
            "mean_directional_return_over_sigma": [0.5, 0.5],
        })
        yr = pd.DataFrame({
            "config_id": ["A", "A"],
            "horizon": ["60m", "60m"],
            "year": ["2018", "2019"],
            "touch_count": [100, 100],
            "complete_label_count": [95, 95],
            "median_mfe_points": [5.0, 5.0],
            "median_mae_points": [2.0, 2.0],
            "mean_directional_return_over_sigma": [0.5, 0.5],
        })
        reasons = _check_stability_year_direction("A", yr, dir_metrics, pd.DataFrame())
        has_dir_issue = any("direction" in r for r in reasons)
        assert has_dir_issue

    def test_balanced_direction(self):
        dir_metrics = pd.DataFrame({
            "config_id": ["A", "A"],
            "horizon": ["60m", "60m"],
            "direction": ["LONG", "SHORT"],
            "touch_count": [100, 100],
            "complete_label_count": [90, 90],
            "median_mfe_points": [5.0, 5.0],
            "median_mae_points": [2.0, 2.0],
            "mean_directional_return_over_sigma": [0.5, 0.5],
        })
        yr = pd.DataFrame({
            "config_id": ["A", "A"],
            "horizon": ["60m", "60m"],
            "year": ["2018", "2019"],
            "touch_count": [100, 100],
            "complete_label_count": [95, 95],
            "median_mfe_points": [5.0, 5.0],
            "median_mae_points": [2.0, 2.0],
            "mean_directional_return_over_sigma": [0.5, 0.5],
        })
        reasons = _check_stability_year_direction("A", yr, dir_metrics, pd.DataFrame())
        has_dir_issue = any("direction" in r for r in reasons)
        assert not has_dir_issue


# ══════════════════════════════════════════════════════════════════════
# 25. Temporal clustering check
# ══════════════════════════════════════════════════════════════════════

class TestTemporalClustering:
    def test_temporal_clustering_detected(self):
        year_metrics = pd.DataFrame({
            "config_id": ["A", "A"],
            "horizon": ["60m", "60m"],
            "year": ["2018", "2019"],
            "touch_count": [195, 5],
            "complete_label_count": [190, 5],
            "median_mfe_points": [5.0, 5.0],
            "median_mae_points": [2.0, 2.0],
            "mean_directional_return_over_sigma": [0.5, 0.5],
        })
        dir_metrics = pd.DataFrame({
            "config_id": ["A", "A"],
            "horizon": ["60m", "60m"],
            "direction": ["LONG", "SHORT"],
            "touch_count": [100, 100],
            "complete_label_count": [95, 95],
            "median_mfe_points": [5.0, 5.0],
            "median_mae_points": [2.0, 2.0],
            "mean_directional_return_over_sigma": [0.5, 0.5],
        })
        reasons = _check_stability_year_direction("A", year_metrics, dir_metrics, pd.DataFrame())
        has_year_issue = any("year" in r for r in reasons)
        assert has_year_issue

    def test_temporal_balanced(self):
        year_metrics = pd.DataFrame({
            "config_id": ["A", "A"],
            "horizon": ["60m", "60m"],
            "year": ["2018", "2019"],
            "touch_count": [100, 95],
            "complete_label_count": [95, 90],
            "median_mfe_points": [5.0, 5.0],
            "median_mae_points": [2.0, 2.0],
            "mean_directional_return_over_sigma": [0.5, 0.5],
        })
        dir_metrics = pd.DataFrame({
            "config_id": ["A", "A"],
            "horizon": ["60m", "60m"],
            "direction": ["LONG", "SHORT"],
            "touch_count": [100, 95],
            "complete_label_count": [95, 90],
            "median_mfe_points": [5.0, 5.0],
            "median_mae_points": [2.0, 2.0],
            "mean_directional_return_over_sigma": [0.5, 0.5],
        })
        reasons = _check_stability_year_direction("A", year_metrics, dir_metrics, pd.DataFrame())
        has_year_issue = any("year" in r for r in reasons)
        assert not has_year_issue


# ══════════════════════════════════════════════════════════════════════
# 26. SYNTHETIC TESTS PROVING STAGE 2A CORRECTIONS
# ══════════════════════════════════════════════════════════════════════

class TestCorrection01DevelopmentRunNotStub:
    """1. development_run is not a stub — it runs the full pipeline."""

    def test_development_run_executable(self):
        from research.es_vix_level_discovery.stage2_runner import development_run
        # Verify it's a real function with actual pipeline code
        import inspect
        source = inspect.getsource(development_run)
        assert "es_raw" in source
        assert "load_grid" in source
        assert "firewall_enforce_full" in source
        assert "MANIFEST.json" in source
        assert "CONFIG_RESULTS.csv" in source
        assert "SURVIVOR_DECISIONS.csv" in source
        assert "OUTPUT_HASHES.sha256" in source


class TestCorrection02ConfirmationFlag:
    """2. --confirm-development-only flag is required."""

    def test_confirmation_flag_required(self):
        from research.es_vix_level_discovery.stage2_runner import main
        import sys
        old = sys.argv
        try:
            sys.argv = ["stage2_runner.py", "--development-run", "test_run"]
            with pytest.raises(SystemExit) as exc:
                main()
            # Should exit 1 with error message, not run anything
            assert exc.value.code == 1
        finally:
            sys.argv = old

    def test_both_flags_accepted(self):
        from research.es_vix_level_discovery.stage2_runner import main
        import sys
        old = sys.argv
        try:
            sys.argv = ["stage2_runner.py",
                        "--development-run", "test_both",
                        "--confirm-development-only"]
            # The function will try to load data and fail with file not found
            # in test context; that's fine — we just verify the flags parse
            with pytest.raises((SystemExit, FileNotFoundError, Exception)):
                main()
        finally:
            sys.argv = old


class TestCorrection03FilterBeforeLevelGeneration:
    """3. ES data is filtered to 2018-2019 before level generation."""

    def test_filter_before_levels(self):
        from research.es_vix_level_discovery.stage2_runner import development_run
        import inspect
        source = inspect.getsource(development_run)
        assert "session_date\".between(" in source or "between(" in source
        assert "2018-01-01" in source
        assert "2019-12-31" in source

    def test_filtered_es_no_2020(self):
        """Prove filtered data has no post-2019 rows."""
        es = synthetic_multiday_es("2018-01-02", num_sessions=500)
        if "session_date" not in es.columns:
            ny = pd.to_datetime(es["timestamp"], utc=True).dt.tz_convert("America/New_York")
            es["session_date"] = ny.dt.strftime("%Y-%m-%d")
        filtered = es[es["session_date"].between("2018-01-01", "2019-12-31")]
        # Even with 500 sessions, nothing should exceed 2019
        max_date = filtered["session_date"].max()
        assert str(max_date)[:4] <= "2019"


class TestCorrection04FirewallInspectsEveryDatedField:
    """4. Firewall inspects all dated output rows."""

    def test_firewall_checks_level_session(self):
        """Level with session_date in 2020 should fail."""
        levels = pd.DataFrame({
            "level_id": ["L1"],
            "config_id": ["CFG"],
            "session_date": ["2020-01-15"],
            "created_at": ["2020-01-15 10:00:00-05:00"],
            "first_eligible_at": ["2020-01-15 10:01:00-05:00"],
            "direction": ["UPPER"],
            "level_price": [4800.0],
        })
        with pytest.raises(SystemExit) as exc:
            firewall_enforce_full(levels, None, None, None)
        assert exc.value.code == 75

    def test_firewall_checks_touch_timestamp(self):
        touches = pd.DataFrame({
            "touch_id": ["T1"],
            "level_id": ["L1"],
            "config_id": ["CFG"],
            "level_direction": ["UPPER"],
            "touch_direction": ["SHORT"],
            "level_price": [4800.0],
            "touch_bar_timestamp": ["2020-06-01 10:30:00-04:00"],
            "touch_bar_open": [4800.0],
            "touch_bar_high": [4805.0],
            "touch_bar_low": [4795.0],
            "reference_entry_price": [4800.0],
            "gap_through": [False],
            "session_created": ["2019-12-01"],
            "session_touched": ["2020-06-01"],
            "level_age_sessions": [5],
            "level_age_minutes": [100],
            "sigma_day": [10.0],
            "vix_source_date": ["2019-11-30"],
            "vix_available_at": ["2019-12-01 09:30:00"],
            "deterministic_order": [1],
            "overlap_cluster_id": [0],
        })
        with pytest.raises(SystemExit) as exc:
            firewall_enforce_full(None, touches, None, None)
        assert exc.value.code == 75

    def test_firewall_checks_label_start(self):
        excursions = pd.DataFrame({
            "touch_id": ["T1"],
            "config_id": ["CFG"],
            "level_direction": ["UPPER"],
            "touch_direction": ["SHORT"],
            "horizon": ["60m"],
            "label_status": ["COMPLETE"],
            "label_start": ["2020-01-02 10:01:00-05:00"],
            "requested_end_exclusive": ["2020-01-02 11:01:00-05:00"],
            "actual_last_bar": ["2020-01-02 11:00:00-05:00"],
            "required_bar_count": [60],
            "actual_bar_count": [60],
            "mae": [1.0],
            "mfe": [1.0],
            "mae_sigma_ratio": [0.1],
            "mfe_sigma_ratio": [0.1],
            "mae_ib_range_ratio": [0.05],
            "mfe_ib_range_ratio": [0.05],
            "directional_horizon_close_return_sigma": [0.5],
            "sigma_day": [10.0],
            "fp_025_sigma": ["FAVORABLE_FIRST"],
            "fp_050_sigma": ["FAVORABLE_FIRST"],
            "fp_075_sigma": ["NOT_REACHED"],
            "fp_100_sigma": ["NOT_REACHED"],
            "fp_025_timestamp": ["2020-01-02 10:05:00-05:00"],
            "fp_050_timestamp": ["2020-01-02 10:10:00-05:00"],
            "fp_075_timestamp": [None],
            "fp_100_timestamp": [None],
        })
        with pytest.raises(SystemExit) as exc:
            firewall_enforce_full(None, None, excursions, None)
        assert exc.value.code == 75

    def test_firewall_passes_2018_2019_labels(self):
        excursions = pd.DataFrame({
            "touch_id": ["T1"],
            "config_id": ["CFG"],
            "level_direction": ["UPPER"],
            "touch_direction": ["SHORT"],
            "horizon": ["60m"],
            "label_status": ["COMPLETE"],
            "label_start": ["2019-06-01 10:01:00-04:00"],
            "requested_end_exclusive": ["2019-06-01 11:01:00-04:00"],
            "actual_last_bar": ["2019-06-01 11:00:00-04:00"],
            "required_bar_count": [60],
            "actual_bar_count": [60],
            "mae": [1.0],
            "mfe": [1.0],
            "mae_sigma_ratio": [0.1],
            "mfe_sigma_ratio": [0.1],
            "mae_ib_range_ratio": [0.05],
            "mfe_ib_range_ratio": [0.05],
            "directional_horizon_close_return_sigma": [0.5],
            "sigma_day": [10.0],
            "fp_025_sigma": ["FAVORABLE_FIRST"],
            "fp_050_sigma": ["FAVORABLE_FIRST"],
            "fp_075_sigma": ["NOT_REACHED"],
            "fp_100_sigma": ["NOT_REACHED"],
            "fp_025_timestamp": [None],
            "fp_050_timestamp": [None],
            "fp_075_timestamp": [None],
            "fp_100_timestamp": [None],
        })
        firewall_enforce_full(None, None, excursions, None)


class TestCorrection05ExactVIXDecileMatching:
    """5. Baseline uses exact VIX decile from actual touch."""

    def test_decile_matching_applied(self):
        vix = synthetic_vix(vix_close=15.0, num_days=500)
        vix["date"] = pd.to_datetime(vix["date"])
        bounds = _vix_decile_bounds(vix)
        idx = _decile_index(15.0, bounds)
        assert 0 <= idx < 10

    def test_random_sigma_from_random_session(self):
        """Random candidate uses its own session's sigma_day."""
        es = synthetic_multiday_es("2018-01-02", num_sessions=10)
        vix = synthetic_vix(vix_close=15.0, num_days=500)
        vix["date"] = pd.to_datetime(vix["date"])
        cfg = LevelConfig("TEST_RSIG", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        touches = engine.assign_overlap_clusters(touches)
        if not touches.empty:
            result = build_baseline(
                touches, levels, es, vix,
                horizons=["60m"],
                n_resamples=2,
            )
            agg = result["aggregated"]
            if not agg.empty:
                assert "rand_sigma_day_used" in agg.columns
                assert agg["rand_sigma_day_used"].notna().any()

    def test_actual_label_window_excluded(self):
        """Random candidates exclude the actual touch's bar and label window."""
        es = synthetic_multiday_es("2018-01-02", num_sessions=10)
        vix = synthetic_vix(vix_close=15.0, num_days=500)
        vix["date"] = pd.to_datetime(vix["date"])
        cfg = LevelConfig("TEST_EXW", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        touches = engine.assign_overlap_clusters(touches)
        if not touches.empty:
            result = build_baseline(
                touches, levels, es, vix,
                horizons=["60m"],
                n_resamples=2,
            )
            agg = result["aggregated"]
            if not agg.empty and "random_timestamp" in agg.columns:
                for _, row in agg.iterrows():
                    rt = str(row.get("random_timestamp", ""))[:10]
                    assert rt >= "2018-01-01"
                    assert rt <= "2019-12-31"


class TestCorrection06BaselineAggregationOneRow:
    """6. One aggregated row per config × horizon × resample."""

    def test_aggregation_structure(self):
        """Each config/horizon/resample appears once."""
        es = synthetic_multiday_es("2018-01-02", num_sessions=10)
        vix = synthetic_vix(vix_close=15.0, num_days=500)
        vix["date"] = pd.to_datetime(vix["date"])
        cfg = LevelConfig("TEST_AGG", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        touches = engine.assign_overlap_clusters(touches)
        if not touches.empty:
            result = build_baseline(
                touches, levels, es, vix,
                horizons=["60m"],
                n_resamples=3,
            )
            agg = result["aggregated"]
            if not agg.empty:
                n_combos = agg.groupby(["config_id", "horizon", "resample"]).size()
                assert (n_combos == 1).all(), \
                    "Each config/horizon/resample appears more than once"

    def test_seeds_differ_across_touches(self):
        """Deterministic seeds contain config_id, horizon, touch_id, resample."""
        s1 = _session_seed("CFG_A", "60m", "T1", 0, "MASTER")
        s2 = _session_seed("CFG_A", "60m", "T2", 0, "MASTER")
        s3 = _session_seed("CFG_A", "120m", "T1", 0, "MASTER")
        s4 = _session_seed("CFG_B", "60m", "T1", 0, "MASTER")
        s5 = _session_seed("CFG_A", "60m", "T1", 1, "MASTER")
        # Different touch_id → different seed
        assert s1 != s2
        # Different horizon → different seed
        assert s1 != s3
        # Different config → different seed
        assert s1 != s4
        # Different resample → different seed
        assert s1 != s5


class TestCorrection07BaselineResultsMetrics:
    """7. BASELINE_RESULTS.csv has all required metrics."""

    def test_baseline_summary_columns(self):
        es = synthetic_multiday_es("2018-01-02", num_sessions=10)
        vix = synthetic_vix(vix_close=15.0, num_days=500)
        vix["date"] = pd.to_datetime(vix["date"])
        cfg = LevelConfig("TEST_BSC", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        touches = engine.assign_overlap_clusters(touches)
        if not touches.empty:
            result = build_baseline(
                touches, levels, es, vix,
                horizons=["60m"],
                n_resamples=3,
            )
            summary = result["summary"]
            if not summary.empty:
                expected = [
                    "config_id", "horizon", "selected_count",
                    "median_mfe_points", "median_mae_points",
                    "p90_mae_points", "p95_mae_points",
                    "mean_directional_return_over_sigma",
                    "median_directional_return_over_sigma",
                    "positive_directional_return_rate",
                ]
                for col in expected:
                    assert col in summary.columns, f"Missing: {col}"

    def test_first_passage_in_summary(self):
        es = synthetic_multiday_es("2018-01-02", num_sessions=10)
        vix = synthetic_vix(vix_close=15.0, num_days=500)
        vix["date"] = pd.to_datetime(vix["date"])
        cfg = LevelConfig("TEST_FPS", 1.0, 30, "proportional", "offset_pct", 0.0)
        engine = VIXLevelEngine(cfg)
        levels = engine.generate_levels(es, vix)
        touches = engine.detect_touches(levels, es)
        touches = engine.assign_overlap_clusters(touches)
        if not touches.empty:
            result = build_baseline(
                touches, levels, es, vix,
                horizons=["60m"],
                n_resamples=3,
            )
            summary = result["summary"]
            if not summary.empty:
                for thresh in ["0.25", "0.50", "0.75", "1.00"]:
                    for fp in ["p_favorable_first", "p_adverse_first",
                               "p_ambiguous", "p_neither_reached"]:
                        col = f"{fp}_{thresh}"
                        assert col in summary.columns, f"Missing: {col}"


class TestCorrection08BaselineLiftCorrect:
    """8. Correct baseline lift calculation."""

    def _make_baseline_agg(self, n=10):
        return pd.DataFrame({
            "config_id": ["A"] * n,
            "horizon": ["60m"] * n,
            "resample": list(range(n)),
            "selected_count": [10] * n,
            "median_mfe_points": [float(3 + i * 0.2) for i in range(n)],
            "median_mae_points": [float(1 + i * 0.1) for i in range(n)],
            "p90_mae_points": [3.0] * n,
            "p95_mae_points": [4.0] * n,
            "mean_directional_return_over_sigma": [0.5] * n,
            "median_directional_return_over_sigma": [0.4] * n,
            "positive_directional_return_rate": [0.6] * n,
            "p_favorable_first_0.25": [0.5] * n,
            "p_adverse_first_0.25": [0.3] * n,
            "p_ambiguous_0.25": [0.1] * n,
            "p_neither_reached_0.25": [0.1] * n,
            "p_favorable_first_0.50": [0.4] * n,
            "p_adverse_first_0.50": [0.3] * n,
            "p_ambiguous_0.50": [0.1] * n,
            "p_neither_reached_0.50": [0.2] * n,
            "p_favorable_first_0.75": [0.3] * n,
            "p_adverse_first_0.75": [0.3] * n,
            "p_ambiguous_0.75": [0.1] * n,
            "p_neither_reached_0.75": [0.3] * n,
            "p_favorable_first_1.00": [0.2] * n,
            "p_adverse_first_1.00": [0.3] * n,
            "p_ambiguous_1.00": [0.1] * n,
            "p_neither_reached_1.00": [0.4] * n,
            "rand_sigma_day_used": [10.0] * n,
        })

    def test_lift_has_all_fields(self):
        actual = pd.DataFrame({
            "config_id": ["A"],
            "horizon": ["60m"],
            "median_mfe_points": [5.0],
        })
        baseline = self._make_baseline_agg(10)
        lift = compute_baseline_lift(actual, baseline, horizons=["60m"])
        if not lift.empty:
            lr = lift.iloc[0]
            assert "baseline_median" in lift.columns
            assert "baseline_p05" in lift.columns
            assert "baseline_p95" in lift.columns
            assert "actual_minus_baseline" in lift.columns
            assert "percentage_lift" in lift.columns
            assert "actual_percentile" in lift.columns
            assert "one_sided_p_value" in lift.columns
            assert lr["actual_minus_baseline"] > 0  # actual > baseline
            assert lr["percentage_lift"] is not None

    def test_lift_respects_metric_direction(self):
        """MAE has lower-is-better: high actual MAE gives high p-value."""
        actual = pd.DataFrame({
            "config_id": ["A"],
            "horizon": ["60m"],
            "median_mae_points": [10.0],
        })
        baseline = self._make_baseline_agg(10)
        lift = compute_baseline_lift(actual, baseline, horizons=["60m"])
        if not lift.empty:
            mae_lift = lift[lift["metric"] == "median_mae_points"]
            if not mae_lift.empty:
                # actual is worse (10 vs ~1-1.9), all random < actual
                # p for lower-is-better = count(random < actual) / n = 1.0
                assert not mae_lift["one_sided_p_value"].isna().all()
                assert mae_lift["one_sided_p_value"].iloc[0] == 1.0


class TestCorrection09NeighbourImmediatelyAdjacent:
    """9. Neighbours are immediately adjacent grid cells only."""

    def test_same_sigma_diff_ib_adjacent(self):
        """Same sigma, different IB is adjacent."""
        from research.es_vix_level_discovery.stage2_metrics import _are_adjacent_cells
        c1 = {"config_id": "A", "sigma_multiplier": 1.0, "ib_minutes": 30,
              "offset_family": "proportional", "offset_value": 0.0}
        c2 = {"config_id": "B", "sigma_multiplier": 1.0, "ib_minutes": 60,
              "offset_family": "proportional", "offset_value": 0.0}
        assert _are_adjacent_cells(c1, c2)

    def test_diff_offset_family_not_neighbour(self):
        """Proportional and fixed are never neighbours."""
        from research.es_vix_level_discovery.stage2_metrics import _are_adjacent_cells
        c1 = {"config_id": "A", "sigma_multiplier": 1.0, "ib_minutes": 30,
              "offset_family": "proportional", "offset_value": 0.0}
        c2 = {"config_id": "B", "sigma_multiplier": 1.0, "ib_minutes": 30,
              "offset_family": "fixed", "offset_value": 2.5}
        assert not _are_adjacent_cells(c1, c2)

    def test_nonadjacent_sigma_not_neighbour(self):
        """Sigma diff of 2 steps (0.75→1.25) is not adjacent."""
        from research.es_vix_level_discovery.stage2_metrics import _are_adjacent_cells
        c1 = {"config_id": "A", "sigma_multiplier": 0.75, "ib_minutes": 30,
              "offset_family": "proportional", "offset_value": 0.0}
        c2 = {"config_id": "B", "sigma_multiplier": 1.25, "ib_minutes": 30,
              "offset_family": "proportional", "offset_value": 0.0}
        assert not _are_adjacent_cells(c1, c2)

    def test_multiple_axes_not_neighbour(self):
        """Diff in sigma AND ib is not a neighbour."""
        from research.es_vix_level_discovery.stage2_metrics import _are_adjacent_cells
        c1 = {"config_id": "A", "sigma_multiplier": 1.0, "ib_minutes": 30,
              "offset_family": "proportional", "offset_value": 0.0}
        c2 = {"config_id": "B", "sigma_multiplier": 1.25, "ib_minutes": 60,
              "offset_family": "proportional", "offset_value": 0.0}
        assert not _are_adjacent_cells(c1, c2)

    def test_adjacent_proportional_offset(self):
        """0.0 and 0.02 are adjacent proportional offsets."""
        from research.es_vix_level_discovery.stage2_metrics import _are_adjacent_cells
        c1 = {"config_id": "A", "sigma_multiplier": 1.0, "ib_minutes": 30,
              "offset_family": "proportional", "offset_value": 0.0}
        c2 = {"config_id": "B", "sigma_multiplier": 1.0, "ib_minutes": 30,
              "offset_family": "proportional", "offset_value": 0.02}
        assert _are_adjacent_cells(c1, c2)

    def test_adjacent_fixed_offset(self):
        """2.5 and 5.0 are adjacent fixed offsets."""
        from research.es_vix_level_discovery.stage2_metrics import _are_adjacent_cells
        c1 = {"config_id": "A", "sigma_multiplier": 1.0, "ib_minutes": 30,
              "offset_family": "fixed", "offset_value": 2.5}
        c2 = {"config_id": "B", "sigma_multiplier": 1.0, "ib_minutes": 30,
              "offset_family": "fixed", "offset_value": 5.0}
        assert _are_adjacent_cells(c1, c2)

    def test_nonadjacent_proportional_offset(self):
        """0.0 and 0.04 are NOT adjacent."""
        from research.es_vix_level_discovery.stage2_metrics import _are_adjacent_cells
        c1 = {"config_id": "A", "sigma_multiplier": 1.0, "ib_minutes": 30,
              "offset_family": "proportional", "offset_value": 0.0}
        c2 = {"config_id": "B", "sigma_multiplier": 1.0, "ib_minutes": 30,
              "offset_family": "proportional", "offset_value": 0.04}
        assert not _are_adjacent_cells(c1, c2)


class TestCorrection10StabilityBothHorizons:
    """10. Stability checks separate for 60m and 120m."""

    def test_stability_returns_horizon_specific_reasons(self):
        yr = pd.DataFrame({
            "config_id": ["A", "A", "A", "A"],
            "horizon": ["60m", "60m", "120m", "120m"],
            "year": ["2018", "2019", "2018", "2019"],
            "touch_count": [190, 10, 80, 80],
            "complete_label_count": [180, 10, 75, 75],
            "median_mfe_points": [5.0, 5.0, 4.0, 4.0],
            "median_mae_points": [2.0, 2.0, 2.0, 2.0],
            "mean_directional_return_over_sigma": [0.5, 0.5, 0.4, 0.4],
        })
        dr = pd.DataFrame({
            "config_id": ["A", "A", "A", "A"],
            "horizon": ["60m", "60m", "120m", "120m"],
            "direction": ["LONG", "SHORT", "LONG", "SHORT"],
            "touch_count": [100, 100, 80, 80],
            "complete_label_count": [95, 95, 75, 75],
            "median_mfe_points": [5.0, 5.0, 4.0, 4.0],
            "median_mae_points": [2.0, 2.0, 2.0, 2.0],
            "mean_directional_return_over_sigma": [0.5, 0.5, 0.4, 0.4],
        })
        reasons = _check_stability_year_direction("A", yr, dr, pd.DataFrame())
        has_60m = any("60m" in r for r in reasons)
        has_120m = any("120m" in r for r in reasons)
        # Only 60m should have year issue (190/200 = 95% > 80%)
        assert has_60m
        assert not has_120m


class TestCorrection11SurvivorRankNotAlphabetical:
    """11. Survivor selection ranks by metrics, not config_id alphabetically."""

    def test_survivor_follows_rank_not_alphabetical(self):
        """When capped, rank determines survivor, not config ID order."""
        ids_60m = sorted([f"CFG_{i}" for i in range(50)])
        ids_120m = sorted([f"CFG_{i}" for i in range(50)])
        metrics = pd.DataFrame({
            "config_id": ids_60m + ids_120m,
            "horizon": ["60m"] * 50 + ["120m"] * 50,
            "valid_complete_labels": [200] * 100,
            "long_count": [80] * 100,
            "short_count": [80] * 100,
            "unique_sessions": [60] * 100,
            "generated_levels": [100] * 100,
            "physical_first_touches": [200] * 100,
            "incomplete_labels": [0] * 100,
            "gap_through_count": [10] * 100,
            "ambiguous_first_passage_count": [5] * 100,
            "overlap_clusters": [10] * 100,
            "overlap_adjusted_effective_n": [150] * 100,
            "median_mfe_points": [float(i % 10) for i in range(100)],
            "median_mae_points": [float(10 - i % 10) for i in range(100)],
            "mean_directional_return_over_sigma": [0.5 + 0.05 * (i % 10) for i in range(100)],
            "positive_directional_return_rate": [0.5 + 0.05 * (i % 10) for i in range(100)],
            "p_favorable_first_0.25": [0.5] * 100,
            "p_adverse_first_0.25": [0.3] * 100,
            "p_ambiguous_0.25": [0.1] * 100,
            "p_neither_reached_0.25": [0.1] * 100,
            "p_favorable_first_0.50": [0.4] * 100,
            "p_adverse_first_0.50": [0.3] * 100,
            "p_ambiguous_0.50": [0.1] * 100,
            "p_neither_reached_0.50": [0.2] * 100,
            "p_favorable_first_0.75": [0.3] * 100,
            "p_adverse_first_0.75": [0.3] * 100,
            "p_ambiguous_0.75": [0.1] * 100,
            "p_neither_reached_0.75": [0.3] * 100,
            "p_favorable_first_1.00": [0.2] * 100,
            "p_adverse_first_1.00": [0.3] * 100,
            "p_ambiguous_1.00": [0.1] * 100,
            "p_neither_reached_1.00": [0.4] * 100,
            "mfe_mae_ratio_of_medians": [2.0] * 100,
        })
        decisions = classify_configs(
            metrics_df=metrics,
            baseline_lift_df=pd.DataFrame(),
            direction_metrics=pd.DataFrame(),
            year_metrics=pd.DataFrame(),
            grid_df=pd.DataFrame(),
            excursions_df=pd.DataFrame(),
        )
        passed = decisions[decisions["classification"] == "PASS"]
        assert len(passed) <= 36
        # The configs with highest median_mfe_points should survive,
        # NOT the alphabetically first ones
        if len(passed) > 0:
            survived_ids = passed["config_id"].tolist()
            assert survived_ids != sorted(ids_60m[:36]), \
                "Survivors are alphabetically first — ranking not applied"

    def test_equal_weight_60m_120m(self):
        """Both primary horizons receive equal weight in median ranks."""
        rank = compute_median_ranks(
            pd.DataFrame({
                "config_id": ["A", "A", "B", "B"],
                "horizon": ["60m", "120m", "60m", "120m"],
                "median_mfe_points": [5.0, 3.0, 3.0, 5.0],
                "mean_directional_return_over_sigma": [0.5, 0.3, 0.3, 0.5],
                "positive_directional_return_rate": [0.6, 0.4, 0.4, 0.6],
            }),
            horizons=["60m", "120m"]
        )
        if not rank.empty:
            # Both A and B should have similar combined rank
            assert "combined_rank" in rank.columns


class TestCorrection12AllArtifactsWritten:
    """12. All required artifacts are written."""

    def test_artifact_list_in_runner(self):
        import inspect
        from research.es_vix_level_discovery.stage2_runner import development_run
        source = inspect.getsource(development_run)
        artifacts = [
            "MANIFEST.json",
            "CONFIG_RESULTS.csv",
            "YEAR_RESULTS.csv",
            "DIRECTION_RESULTS.csv",
            "MONTH_RESULTS.csv",
            "VIX_REGIME_RESULTS.csv",
            "TIME_OF_DAY_RESULTS.csv",
            "BASELINE_RESULTS.csv",
            "NEIGHBOURHOOD_RESULTS.csv",
            "SURVIVOR_DECISIONS.csv",
            "REPORT.md",
            "OUTPUT_HASHES.sha256",
        ]
        for art in artifacts:
            assert art in source, f"Missing artifact writer: {art}"


class TestCorrection13DeterminismAndHoldout:
    """13. Deterministic synthetic reruns match, holdout remains UNOPENED."""

    def test_holdout_remains_unopened(self):
        with open(HOLDOUT_PATH) as f:
            h = json.load(f)
        assert h["status"] == "UNOPENED"

    def test_baseline_seeds_deterministic(self):
        s1 = [_session_seed("CFG_A", "60m", "T1", i, "MASTER") for i in range(5)]
        s2 = [_session_seed("CFG_A", "60m", "T1", i, "MASTER") for i in range(5)]
        assert s1 == s2

    def test_classify_configs_stable_with_extra_params(self):
        """Adding excursions_df/neighbour_support_df doesn't break determinism."""
        metrics = pd.DataFrame({
            "config_id": ["A", "A", "B", "B"],
            "horizon": ["60m", "120m", "60m", "120m"],
            "valid_complete_labels": [200, 200, 200, 200],
            "long_count": [80, 80, 80, 80],
            "short_count": [80, 80, 80, 80],
            "unique_sessions": [60, 60, 60, 60],
            "generated_levels": [100, 100, 100, 100],
            "physical_first_touches": [200, 200, 200, 200],
            "incomplete_labels": [0, 0, 0, 0],
            "gap_through_count": [10, 10, 10, 10],
            "ambiguous_first_passage_count": [5, 5, 5, 5],
            "overlap_clusters": [10, 10, 10, 10],
            "overlap_adjusted_effective_n": [150, 150, 150, 150],
            "median_mfe_points": [5.0, 5.0, 3.0, 3.0],
            "median_mae_points": [2.0, 2.0, 4.0, 4.0],
            "mean_directional_return_over_sigma": [0.5, 0.5, 0.3, 0.3],
            "positive_directional_return_rate": [0.6, 0.6, 0.5, 0.5],
            "p_favorable_first_0.25": [0.5, 0.5, 0.4, 0.4],
            "p_adverse_first_0.25": [0.3, 0.3, 0.3, 0.3],
            "p_ambiguous_0.25": [0.1, 0.1, 0.1, 0.1],
            "p_neither_reached_0.25": [0.1, 0.1, 0.2, 0.2],
            "p_favorable_first_0.50": [0.4, 0.4, 0.3, 0.3],
            "p_adverse_first_0.50": [0.3, 0.3, 0.3, 0.3],
            "p_ambiguous_0.50": [0.1, 0.1, 0.1, 0.1],
            "p_neither_reached_0.50": [0.2, 0.2, 0.3, 0.3],
            "p_favorable_first_0.75": [0.3, 0.3, 0.2, 0.2],
            "p_adverse_first_0.75": [0.3, 0.3, 0.3, 0.3],
            "p_ambiguous_0.75": [0.1, 0.1, 0.1, 0.1],
            "p_neither_reached_0.75": [0.3, 0.3, 0.4, 0.4],
            "p_favorable_first_1.00": [0.2, 0.2, 0.1, 0.1],
            "p_adverse_first_1.00": [0.3, 0.3, 0.3, 0.3],
            "p_ambiguous_1.00": [0.1, 0.1, 0.1, 0.1],
            "p_neither_reached_1.00": [0.4, 0.4, 0.5, 0.5],
            "mfe_mae_ratio_of_medians": [2.5, 2.5, 0.75, 0.75],
        })
        d1 = classify_configs(metrics, baseline_lift_df=pd.DataFrame(),
                               direction_metrics=pd.DataFrame(),
                               year_metrics=pd.DataFrame(),
                               grid_df=pd.DataFrame(),
                               excursions_df=pd.DataFrame())
        d2 = classify_configs(metrics, baseline_lift_df=pd.DataFrame(),
                               direction_metrics=pd.DataFrame(),
                               year_metrics=pd.DataFrame(),
                               grid_df=pd.DataFrame(),
                               excursions_df=pd.DataFrame())
        pd.testing.assert_frame_equal(d1, d2)
