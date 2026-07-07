import math
from pathlib import Path

import pandas as pd
import pytest

from src.forward_ledger import (
    CONFIGS,
    PF_TARGETS,
    SCENARIO_FAMILIES,
    SELECTED_PARAMS,
    build_normalized_pool,
    build_scenarios,
    gross_point_metrics,
    require_columns,
    summarize_pool,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


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


def test_missing_mae_mfe_is_explicit_not_imputed():
    pool = build_normalized_pool(REPO_ROOT, "primary_150r")
    assert "mae_pts" in pool.columns and "mfe_pts" in pool.columns
    assert pool["mae_pts"].isna().all()
    assert pool["mfe_pts"].isna().all()
    assert set(pool["mae_mfe_status"]) == {"missing_source_not_imputed"}


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


def test_required_column_failure_is_honest():
    with pytest.raises(ValueError, match="missing required columns"):
        require_columns(pd.DataFrame({"pnl": [1.0]}), {"pnl", "cap"}, "bad_source.csv")
