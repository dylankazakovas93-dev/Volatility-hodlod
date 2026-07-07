import math
import os
from pathlib import Path

import pandas as pd
import pytest

from src.forward_ledger import (
    CONFIGS,
    PF_TARGETS,
    SCENARIO_FAMILIES,
    SELECTED_PARAMS,
    build_final_calendar_blocks,
    build_final_forward_ledger,
    build_final_point_scale_scenarios,
    build_final_scenario_manifest,
    build_normalized_pool,
    build_rr_config_manifest,
    build_scenarios,
    build_two_month_forward_horizon,
    build_two_month_windows,
    gross_point_metrics,
    load_excursion_context,
    require_columns,
    summarize_pool,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
CONTINUOUS_BARS = Path(
    os.environ.get("NQ_1M_2018_2026_CSV", REPO_ROOT / "data/nq_1m/nq_continuous_2018_2026_1m.csv")
)


def test_gross_profit_loss_net_pf_invariants():
    pnl = pd.Series([10.0, -4.0, 0.0, 2.0, -1.0])
    m = gross_point_metrics(pnl)
    assert m.gross_profit_pts == 12.0
    assert m.gross_loss_pts == 5.0
    assert m.net_pts == 7.0
    assert math.isclose(m.points_pf, 2.4)
    assert m.net_pts > 0 and m.points_pf > 1.0

    neg = gross_point_metrics(pd.Series([1.0, -3.0]))
    assert neg.net_pts < 0 and neg.points_pf < 1.0


def test_selected_rolling_pf_summary_rows_reproduce_exact_requested_numbers():
    summary = pd.read_csv(REPO_ROOT / "outputs/og_regime_killswitch/killswitch_summary.csv")
    expected = {
        "primary_150r": {
            "PF_R": 1.234475099113488,
            "avg_R_per_trade": 0.0516127464184325,
            "max_dd_R": -14.531184481261048,
            "PF_pts": 1.44833308257292,
            "baseline_PF_R": 1.0764739550930975,
            "baseline_PF_pts": 1.2781647580792608,
        },
        "operational_100r": {
            "PF_R": 1.2491153590474051,
            "avg_R_per_trade": 0.0459327904961629,
            "max_dd_R": -10.96913872102261,
            "PF_pts": 1.568369164695021,
            "baseline_PF_R": 1.0231108277534768,
            "baseline_PF_pts": 1.298998596872805,
        },
    }
    for config, exp in expected.items():
        selected = summary[
            (summary["config"] == config)
            & (summary["mechanism"] == "rolling_pf")
            & (summary["params"] == SELECTED_PARAMS)
        ].iloc[0]
        baseline = summary[(summary["config"] == config) & (summary["mechanism"] == "baseline_always_on")].iloc[0]
        assert selected["PF_R"] == pytest.approx(exp["PF_R"])
        assert selected["avg_R_per_trade"] == pytest.approx(exp["avg_R_per_trade"])
        assert selected["max_dd_R"] == pytest.approx(exp["max_dd_R"])
        assert selected["PF_pts"] == pytest.approx(exp["PF_pts"])
        assert baseline["PF_R"] == pytest.approx(exp["baseline_PF_R"])
        assert baseline["PF_pts"] == pytest.approx(exp["baseline_PF_pts"])


def test_normalized_pools_are_separate_and_keep_geometry():
    one_rr = build_normalized_pool(REPO_ROOT, "operational_100r")
    one_five_rr = build_normalized_pool(REPO_ROOT, "primary_150r")

    assert set(one_rr["pool_id"]) == {"1rr"}
    assert set(one_five_rr["pool_id"]) == {"1_5rr"}
    assert (one_rr["target_pts"] == one_rr["effective_stop_pts"]).all()
    assert (one_five_rr["target_pts"] == one_five_rr["effective_stop_pts"] * 1.5).all()
    assert one_rr["effective_stop_pts"].max() >= 200.0
    assert one_five_rr["effective_stop_pts"].max() >= 200.0


@pytest.fixture(scope="session")
def excursion_context():
    if not CONTINUOUS_BARS.exists():
        pytest.skip(f"continuous 2018-2026 1m bars not available at {CONTINUOUS_BARS}")
    return load_excursion_context(REPO_ROOT, CONTINUOUS_BARS)


def test_actual_intratrade_mae_mfe_are_computed_from_1m_bars(excursion_context):
    pool = build_normalized_pool(REPO_ROOT, "primary_150r", excursion_context)
    assert "mae_pts" in pool.columns and "mfe_pts" in pool.columns
    assert pool["mae_pts"].notna().all()
    assert pool["mfe_pts"].notna().all()
    assert (pool["mae_pts"] >= 0.0).all()
    assert (pool["mfe_pts"] >= 0.0).all()
    assert set(pool["mae_mfe_status"]) == {"computed_from_1m_ohlc_entry_to_exit_inclusive"}
    assert set(pool["mae_mfe_resolution"]) == {"1m_ohlc_bar_extrema"}
    assert (pool["intratrade_bar_count"] >= 1).all()

    tp = pool[pool["exit_reason"] == "TP"]
    sl = pool[pool["exit_reason"] == "SL"]
    assert (tp["mfe_pts"] + 1e-9 >= tp["target_pts"]).all()
    assert (sl["mae_pts"] + 1e-9 >= sl["effective_stop_pts"]).all()


def test_selected_switch_effective_metrics_recompute_from_trade_pool():
    expected = {
        "primary_150r": {"points_pf": 1.44833308257292, "PF_R": 1.234475099113488},
        "operational_100r": {"points_pf": 1.568369164695021, "PF_R": 1.2491153590474051},
    }
    for config, exp in expected.items():
        pool = build_normalized_pool(REPO_ROOT, config)
        summary = summarize_pool(pool)
        assert summary["points_pf"] == pytest.approx(exp["points_pf"])
        assert summary["PF_R"] == pytest.approx(exp["PF_R"])


def test_scenario_manifests_have_complete_block_weights():
    source_pool = pd.concat([build_normalized_pool(REPO_ROOT, c) for c in CONFIGS], ignore_index=True)
    manifests, block_weights = build_scenarios(source_pool)
    assert len(manifests) == len(CONFIGS) * len(PF_TARGETS) * len(SCENARIO_FAMILIES)

    manifest_ids = {m["scenario_id"] for m in manifests}
    assert set(block_weights["scenario_id"]) == manifest_ids
    for scenario_id, rows in block_weights.groupby("scenario_id"):
        assert rows["scenario_weight"].sum() == pytest.approx(1.0)
        assert (rows["scenario_weight"] > 0).all()

    for target in PF_TARGETS:
        for family in SCENARIO_FAMILIES:
            for config in CONFIGS:
                sid = f"{config}__pf_{target:.2f}__{family}"
                assert sid in manifest_ids


def test_rr_switch_and_two_month_horizon_are_explicit(excursion_context):
    pools = {config: build_normalized_pool(REPO_ROOT, config, excursion_context) for config in CONFIGS}
    rr_manifest = build_rr_config_manifest(pools)
    assert {row["rr_config_id"] for row in rr_manifest} == {"1rr", "1_5rr"}
    assert {row["target_r"] for row in rr_manifest} == {1.0, 1.5}
    assert all(row["forward_horizon_months"] == 2 for row in rr_manifest)

    source_pool = pd.concat(pools.values(), ignore_index=True)
    windows = build_two_month_windows(source_pool)
    assert not windows.empty
    assert set(windows["rr_config_id"]) == {"1rr", "1_5rr"}
    assert set(windows["horizon_months"]) == {2}
    assert (windows["n_trades"] < len(source_pool)).all()
    assert windows["median_mae_pts"].notna().all()
    assert windows["median_mfe_pts"].notna().all()

    manifests, _ = build_scenarios(source_pool)
    horizon = build_two_month_forward_horizon(windows, manifests)
    assert horizon["forward_horizon_id"] == "two_calendar_months"
    assert horizon["rr_switch_field"] == "rr_config_id"
    assert set(horizon["configs"]) == set(CONFIGS)


def test_final_prop_lab_ledgers_are_separate_and_not_derived(excursion_context):
    one_rr_pool = build_normalized_pool(REPO_ROOT, "operational_100r", excursion_context)
    one_five_pool = build_normalized_pool(REPO_ROOT, "primary_150r", excursion_context)
    one_rr = build_final_forward_ledger(one_rr_pool, "1rr")
    one_five = build_final_forward_ledger(one_five_pool, "1_5rr")

    assert set(one_rr["rr_config_id"]) == {"1rr"}
    assert set(one_five["rr_config_id"]) == {"1_5rr"}
    assert set(one_rr["config"]) == {"operational_100r"}
    assert set(one_five["config"]) == {"primary_150r"}
    assert (one_rr["target_R"] - 1.0).abs().max() < 1e-12
    assert (one_five["target_R"] - 1.5).abs().max() < 1e-12

    key_cols = ["source_ledger_id", "source_year", "source_month", "source_session_date", "entry_time"]
    paired = one_rr.merge(one_five, on=key_cols, suffixes=("_1rr", "_1_5rr"))
    assert not paired.empty
    differs = (
        (paired["exit_time_1rr"] != paired["exit_time_1_5rr"])
        | (paired["exit_reason_1rr"] != paired["exit_reason_1_5rr"])
        | (paired["holding_duration_1rr"] != paired["holding_duration_1_5rr"])
    )
    assert differs.any(), "1.5RR must come from independent replay, not 1RR winner multiplication"


def test_final_packet_rescaling_preserves_relationships_and_identity(excursion_context):
    pool = build_normalized_pool(REPO_ROOT, "primary_150r", excursion_context)
    ledger = build_final_forward_ledger(pool, "1_5rr")
    row = ledger[ledger["effective_exit_reason"] != "FLAT"].iloc[0]
    scale = 125.0
    assert row["pnl_R"] * scale == pytest.approx(row["pnl_points"] / row["raw_stop_points"] * scale)
    assert row["target_R"] * scale == pytest.approx(187.5)
    assert row["mae_R"] * scale == pytest.approx(row["mae_points"] / row["raw_stop_points"] * scale)
    assert row["mfe_R"] * scale == pytest.approx(row["mfe_points"] / row["raw_stop_points"] * scale)
    assert row["exit_reason"] in {"TP", "SL", "BE", "cutoff"}


def test_final_scenarios_keep_pf_and_point_scale_independent(excursion_context):
    pools = {
        "1rr": build_final_forward_ledger(build_normalized_pool(REPO_ROOT, "operational_100r", excursion_context), "1rr"),
        "1_5rr": build_final_forward_ledger(build_normalized_pool(REPO_ROOT, "primary_150r", excursion_context), "1_5rr"),
    }
    blocks = build_final_calendar_blocks(pools)
    manifest = build_final_scenario_manifest(pools, blocks)
    scales = build_final_point_scale_scenarios(pools)

    assert len(manifest["scenarios"]) == 2 * len(PF_TARGETS) * len(SCENARIO_FAMILIES)
    assert {s["pf_assumption_id"] for s in manifest["scenarios"]} == {
        "FORWARD_PF_ASSUMPTION_1_35",
        "FORWARD_PF_ASSUMPTION_1_50",
        "FORWARD_PF_ASSUMPTION_1_65",
    }
    for scenario in manifest["scenarios"]:
        assert scenario["within_calibration_band"]
        assert scenario["point_scale_independent_from_pf"]
        assert scenario["negative_blocks_remain_eligible"]
        assert any(b["negative_block"] for b in scenario["block_weights"])
    assert {s["point_scale_scenario_id"] for s in scales} == {
        "scale_central",
        "scale_minus_10",
        "scale_plus_10",
        "scale_minus_15",
        "scale_plus_15",
        "scale_minus_20",
        "scale_plus_20",
    }
    assert all(s["scale_field"] == "raw_stop_points" for s in scales)


def test_final_calendar_blocks_use_july_august_weights_and_anchor_once():
    blocks = pd.read_csv(REPO_ROOT / "artifacts/forward_ledger/final/calendar_blocks.csv")
    assert {7, 8}.issubset(set(blocks["source_month"]))
    ja = blocks[blocks["source_month"].isin([7, 8])]
    assert not ja.empty
    assert (ja["july_august_blend_weight"] == 1.0).all()
    assert blocks["negative_block"].any()

    anchor = pd.read_csv(REPO_ROOT / "artifacts/forward_ledger/final/realized_anchor.csv")
    assert len(anchor) == 1
    assert anchor["date"].iloc[0] == "2026-07-07"
    assert anchor["realized_pnl_points"].iloc[0] == pytest.approx(150.0)
    assert anchor["status"].iloc[0] == "REALIZED"


def test_required_column_failure_is_honest():
    with pytest.raises(ValueError, match="missing required columns"):
        require_columns(pd.DataFrame({"pnl": [1.0]}), {"pnl", "cap"}, "bad_source.csv")
