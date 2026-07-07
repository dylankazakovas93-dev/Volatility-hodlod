# Forward Ledger Artifacts

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
