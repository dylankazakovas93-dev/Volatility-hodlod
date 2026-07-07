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
    build_rr_config_manifest,
    build_scenarios,
    build_two_month_forward_horizon,
    build_two_month_windows,
    load_excursion_context,
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


def source_path_label(path: str) -> str:
    p = Path(path)
    try:
        return str(p.relative_to(REPO_ROOT))
    except ValueError:
        return f"external:{p.name}"


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
historical source libraries, not the two-month forward ledger. They exist so
Prop Lab can sample historically backed trade packets. Use
`rr_config_manifest.json` to switch between RR configurations:

- `rr_config_id=1rr` -> `historical_trade_pool_1rr.csv`
- `rr_config_id=1_5rr` -> `historical_trade_pool_1_5rr.csv`

Use `two_month_forward_horizon.json` and `two_month_historical_windows.csv`
for the requested two-calendar-month forward horizon.

Point scale fields (`raw_stop_pts`,
`effective_stop_pts`, `target_pts`, `pnl_pts_*`, `mae_pts`, `mfe_pts`) are
kept separate from expectancy fields (`exit_reason`, `effective_exit_reason`,
`is_flat`, scenario block weights).

MAE/MFE are recomputed from raw 1-minute OHLC bars for every historical trade:

- 2013-2015 uses committed external compressed bars under
  `data/external_2013_2015/raw/`.
- 2018-2026 uses the continuous NQ 1-minute file supplied locally as
  `data/nq_1m/nq_continuous_2018_2026_1m.csv` or through
  `NQ_1M_2018_2026_CSV`.

The excursion scan is actual 1-minute bar-extrema from recorded entry time
through recorded exit time, inclusive. It is not an estimate. The limitation is
bar resolution: the source does not provide tick ordering inside the entry or
exit minute, so intrabar sequence within those minutes cannot be resolved.

Downstream Monte Carlo should use `forward_source_pool.csv` as reusable packets
and `scenario_manifests.json` plus `scenario_block_weights.csv` as explicit
scenario metadata. It should select `rr_config_id` first, then a two-month
horizon, then scenario weights. No file here is a single seeded 15-trade ledger
or a p10/p50/p90 example path.
"""
    (out_dir / "README.md").write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="artifacts/forward_ledger")
    parser.add_argument(
        "--continuous-2018-2026-bars",
        default=None,
        help="Path to NQ continuous 2018-2026 1-minute OHLC CSV. Defaults to data/nq_1m/... or NQ_1M_2018_2026_CSV.",
    )
    args = parser.parse_args()

    out_dir = REPO_ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    excursion_context = load_excursion_context(REPO_ROOT, args.continuous_2018_2026_bars)
    pools = {config: build_normalized_pool(REPO_ROOT, config, excursion_context) for config in CONFIGS}
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
    rr_config_manifest = build_rr_config_manifest(pools)
    two_month_windows = build_two_month_windows(source_pool)
    two_month_horizon = build_two_month_forward_horizon(two_month_windows, manifests)

    write_json(out_dir / "point_scale_scenarios.json", point_scale_scenarios)
    write_json(out_dir / "expectancy_scenarios.json", expectancy_scenarios)
    write_json(out_dir / "rr_config_manifest.json", rr_config_manifest)
    write_json(out_dir / "two_month_forward_horizon.json", two_month_horizon)
    write_json(out_dir / "scenario_manifests.json", manifests)
    block_weights.to_csv(out_dir / "scenario_block_weights.csv", index=False)
    two_month_windows.to_csv(out_dir / "two_month_historical_windows.csv", index=False)
    write_readme(out_dir)

    pool_summaries = {
        config: {
            "baseline": summarize_pool(pool, pnl_col="pnl_pts_baseline"),
            "selected_switch_effective": summarize_pool(pool, pnl_col="pnl_pts_effective"),
        }
        for config, pool in pools.items()
    }
    mae_mfe = {
        config: {
            "mae_pts_missing": int(pool["mae_pts"].isna().sum()),
            "mfe_pts_missing": int(pool["mfe_pts"].isna().sum()),
            "rows": int(len(pool)),
            "status": sorted(pool["mae_mfe_status"].unique().tolist()),
            "resolution": sorted(pool["mae_mfe_resolution"].unique().tolist()),
            "intratrade_bar_count_min": int(pool["intratrade_bar_count"].min()),
            "intratrade_bar_count_median": float(pool["intratrade_bar_count"].median()),
            "intratrade_bar_count_max": int(pool["intratrade_bar_count"].max()),
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
        "excursion_sources": {
            "bars_2013_2015": source_path_label(excursion_context.bars_2013_2015_path),
            "bars_2018_2026": source_path_label(excursion_context.bars_2018_2026_path),
            "bars_2018_2026_default": "data/nq_1m/nq_continuous_2018_2026_1m.csv",
            "bars_2018_2026_env": "NQ_1M_2018_2026_CSV",
            "method": "actual_1m_ohlc_bar_extrema_from_recorded_entry_to_exit_inclusive",
            "limitation": "1-minute OHLC does not contain tick ordering inside the entry or exit minute.",
        },
        "selected_summary_rows": selected_summary_rows(),
        "pool_summaries": pool_summaries,
        "mae_mfe": mae_mfe,
        "scenario_counts": {
            "point_scale_scenarios": len(point_scale_scenarios),
            "expectancy_scenarios": len(expectancy_scenarios),
            "scenario_manifests": len(manifests),
            "scenario_block_weight_rows": int(len(block_weights)),
            "rr_configs": len(rr_config_manifest),
            "two_month_historical_windows": int(len(two_month_windows)),
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
