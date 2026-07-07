#!/usr/bin/env python3
"""Build forward-ledger source pools and scenario manifests.

The script reads committed OG regime-killswitch outputs only. It does not
re-simulate historical trades and does not modify frozen strategy outputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.forward_ledger import (  # noqa: E402
    CONFIGS,
    PF_TARGETS,
    SCENARIO_FAMILIES,
    SELECTED_PARAMS,
    assert_pf_invariants,
    build_expectancy_scenarios,
    build_normalized_pool,
    build_point_scale_scenarios,
    build_scenarios,
    summarize_pool,
    write_json,
)

SOURCE_DATA_COMMIT = "12a0f779e953d99a7576d4ecec9909f69dfc4159"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def selected_summary_rows() -> dict:
    summary = pd.read_csv(REPO_ROOT / "outputs/og_regime_killswitch/killswitch_summary.csv")
    rows = {}
    for config in CONFIGS:
        selected = summary[
            (summary["config"] == config)
            & (summary["mechanism"] == "rolling_pf")
            & (summary["params"] == SELECTED_PARAMS)
        ]
        baseline = summary[(summary["config"] == config) & (summary["mechanism"] == "baseline_always_on")]
        if len(selected) != 1 or len(baseline) != 1:
            raise ValueError(f"could not find unique selected/baseline summary rows for {config}")
        rows[config] = {
            "baseline": baseline.iloc[0].to_dict(),
            "selected_rolling_pf_w100_t1_1_symmetric": selected.iloc[0].to_dict(),
        }
    return rows


def write_readme(out_dir: Path) -> None:
    text = """# Forward Ledger Artifacts

These artifacts are generated from `research/og-regime-killswitch` committed
outputs. They use the selected rolling-PF kill switch:

- rolling points-PF
- trailing 100 completed trades
- threshold 1.10
- symmetric re-entry

`historical_trade_pool_1rr.csv` and `historical_trade_pool_1_5rr.csv` are
separate source pools. Point scale fields (`raw_stop_pts`,
`effective_stop_pts`, `target_pts`, `pnl_pts_*`, `mae_pts`, `mfe_pts`) are
kept separate from expectancy fields (`exit_reason`, `effective_exit_reason`,
`is_flat`, scenario block weights).

MAE/MFE are intentionally null because the OG chronological source ledgers and
2013-2015 external source data do not contain enough committed information to
compute them for the complete pool. The columns are present with
`mae_mfe_status=missing_source_not_imputed`.

Downstream Monte Carlo should use `forward_source_pool.csv` as reusable packets
and `scenario_manifests.json` plus `scenario_block_weights.csv` as explicit
scenario metadata. No file here is a single seeded 15-trade ledger or a
p10/p50/p90 example path.
"""
    (out_dir / "README.md").write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="artifacts/forward_ledger")
    args = parser.parse_args()

    out_dir = REPO_ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    pools = {config: build_normalized_pool(REPO_ROOT, config) for config in CONFIGS}
    for pool in pools.values():
        assert_pf_invariants(pool["pnl_pts_effective"])
        assert_pf_invariants(pool["pnl_pts_baseline"])

    pools["operational_100r"].to_csv(out_dir / "historical_trade_pool_1rr.csv", index=False)
    pools["primary_150r"].to_csv(out_dir / "historical_trade_pool_1_5rr.csv", index=False)

    source_pool = pd.concat([pools["operational_100r"], pools["primary_150r"]], ignore_index=True)
    source_pool.to_csv(out_dir / "forward_source_pool.csv", index=False)

    point_scale_scenarios = build_point_scale_scenarios(source_pool)
    manifests, block_weights = build_scenarios(source_pool)
    expectancy_scenarios = build_expectancy_scenarios(manifests)

    write_json(out_dir / "point_scale_scenarios.json", point_scale_scenarios)
    write_json(out_dir / "expectancy_scenarios.json", expectancy_scenarios)
    write_json(out_dir / "scenario_manifests.json", manifests)
    block_weights.to_csv(out_dir / "scenario_block_weights.csv", index=False)
    write_readme(out_dir)

    pool_summaries = {
        config: {
            "baseline": summarize_pool(pool, pnl_col="pnl_pts_baseline"),
            "selected_switch_effective": summarize_pool(pool, pnl_col="pnl_pts_effective"),
        }
        for config, pool in pools.items()
    }
    missing_mae_mfe = {
        config: {
            "mae_pts_missing": int(pool["mae_pts"].isna().sum()),
            "mfe_pts_missing": int(pool["mfe_pts"].isna().sum()),
            "rows": int(len(pool)),
            "reason": "OG chronological source ledgers do not include MAE/MFE; 2013-2015 raw bars absent.",
        }
        for config, pool in pools.items()
    }
    summary = {
        "status": "forward_ledger_artifacts_built",
        "source_data_commit": SOURCE_DATA_COMMIT,
        "source_branch": "research/og-regime-killswitch",
        "selected_regime": {
            "mechanism": "rolling_pf",
            "params": SELECTED_PARAMS,
            "rolling_window_completed_trades": 100,
            "threshold_points_pf": 1.10,
            "reentry": "symmetric",
        },
        "configs": CONFIGS,
        "selected_summary_rows": selected_summary_rows(),
        "pool_summaries": pool_summaries,
        "missing_mae_mfe": missing_mae_mfe,
        "scenario_counts": {
            "point_scale_scenarios": len(point_scale_scenarios),
            "expectancy_scenarios": len(expectancy_scenarios),
            "scenario_manifests": len(manifests),
            "scenario_block_weight_rows": int(len(block_weights)),
            "pf_targets": list(PF_TARGETS),
            "families": list(SCENARIO_FAMILIES),
        },
        "artifacts": {
            p.name: sha256_file(p)
            for p in sorted(out_dir.iterdir())
            if p.is_file() and p.name != "forward_ledger_summary.json"
        },
    }
    write_json(out_dir / "forward_ledger_summary.json", summary)
    print(json.dumps(summary["scenario_counts"], indent=2))
    print(f"wrote {out_dir}")


if __name__ == "__main__":
    main()
