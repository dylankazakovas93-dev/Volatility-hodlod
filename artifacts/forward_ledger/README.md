# Forward Ledger Artifacts

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
