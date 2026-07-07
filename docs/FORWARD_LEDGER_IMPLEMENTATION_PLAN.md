# Forward Ledger Implementation Plan

## Scope

Build reusable forward-ledger artifacts for the OG regime kill-switch branch.
The forward source must use the actual selected regime switch:

- mechanism: `rolling_pf`
- window: `100` completed trades
- threshold: `1.10`
- re-entry: `symmetric`

The plain frozen strict-engine PF around `1.29` is not the forward regime
config. It is only a historical baseline context.

Do not modify frozen strategy rules, frozen configs, or historical trade
results. Forward point scale and forward expectancy are separate dimensions:
point scale controls geometry and point magnitudes; expectancy controls which
historical trade packets are active/flat and the outcome mixture/chronology.

## Exact Source Files

- `src/og_regime_killswitch.py`: rolling PF, diagnostics, CUSUM, streak
  kill-switch implementations and metric helpers.
- `scripts/og_regime_killswitch_assemble.py`: assembles chronological
  trade sequences for `primary_150r` and `operational_100r`.
- `scripts/og_regime_killswitch_backtest.py`: runs the 62-variant
  kill-switch backtest and writes selected trigger logs.
- `outputs/og_regime_killswitch/killswitch_summary.csv`: master result
  table for all 62 variants.
- `outputs/og_regime_killswitch/primary_150r_trigger_log_rolling_pf_w100_t1.1_symmetric.csv`:
  selected 1.5R trigger log.
- `outputs/og_regime_killswitch/operational_100r_trigger_log_rolling_pf_w100_t1.1_symmetric.csv`:
  selected 1RR trigger log.
- `outputs/og_regime_killswitch/primary_150r_full_chronological_trades.csv`:
  full chronological 1.5R source ledger.
- `outputs/og_regime_killswitch/operational_100r_full_chronological_trades.csv`:
  full chronological 1RR source ledger.
- `data/external_2013_2015/raw/glbx-mdp3-20130101-20151231.ohlcv-1m.csv.zst`:
  committed raw Databento 2013-2015 1-minute OHLC source. It contains
  outright contracts and calendar spreads, so excursion code must rebuild the
  canonical continuous series by keeping only standard quarterly NQ contracts
  and selecting the highest-volume contract per UTC date.
- `data/nq_1m/nq_continuous_2018_2026_1m.csv`: required local ignored
  2018-2026 continuous 1-minute OHLC source, or equivalent path supplied via
  `NQ_1M_2018_2026_CSV` / `--continuous-2018-2026-bars`.
- `configs/OG_PRIMARY_150R.yaml`: locked 1.5R config.
- `configs/OG_OPERATIONAL_100R.yaml`: locked 1RR config.
- `docs/OG_REGIME_KILLSWITCH_MECHANISMS.md`: mechanism definitions.
- `docs/OG_REGIME_KILLSWITCH_RESULTS.md`: 62-variant result narrative.
- `docs/OG_REGIME_KILLSWITCH_YOY_TABLE.md`: baseline-vs-switch
  points-PF/year table.
- `tests/test_regime_killswitch_causality.py`: causality proof for the
  mechanism family.
- `src/metrics.py`: reusable profit factor and max drawdown helpers.

## Relevant Schemas

### Full Chronological Trades

Files:

- `outputs/og_regime_killswitch/primary_150r_full_chronological_trades.csv`
- `outputs/og_regime_killswitch/operational_100r_full_chronological_trades.csv`

Columns:

- identity/time: `level_id`, `session_date`, `year`, `side`, `entry_time`,
  `exit_time`, `source`
- prices/geometry: `entry_price`, `exit_price`, `level`, `anchor`, `cap`
- outcome: `exit_reason`, `pnl`, `gap_through`

Semantics:

- `cap` is the stop distance in points under the locked core stop formula.
- `target_pts` is `cap * 1.5` for `primary_150r` and `cap * 1.0` for
  `operational_100r`.
- `pnl` is the unfiltered historical trade P&L in points.
- `source` is one of external 2013-2015, build years, or validation.

### Trigger Logs

Files:

- `outputs/og_regime_killswitch/primary_150r_trigger_log_rolling_pf_w100_t1.1_symmetric.csv`
- `outputs/og_regime_killswitch/operational_100r_trigger_log_rolling_pf_w100_t1.1_symmetric.csv`

Columns:

- `session_date`, `year`, `entry_time`, `is_flat`

Semantics:

- `is_flat=True` means the rolling PF switch would skip that trade, so
  effective P&L/R is zero.
- The state is causal: row `i` uses only rows strictly before `i`.

### Kill-Switch Summary

File:

- `outputs/og_regime_killswitch/killswitch_summary.csv`

Columns:

- metrics: `n_trades`, `net_pts`, `total_R`, `PF_pts`, `PF_R`,
  `avg_R_per_trade`, `max_dd_pts`, `max_dd_R`, `n_flat_trades`
- variant identity: `mechanism`, `params`, `config`
- flat stats: `flat_n_flat_runs`, `flat_n_trades_flat`,
  `flat_flat_span_days`

Selected rows to verify:

- `primary_150r`, `rolling_pf`,
  `window=100,threshold=1.1,reentry=symmetric`
- `operational_100r`, `rolling_pf`,
  `window=100,threshold=1.1,reentry=symmetric`

## Missing/Derived Required Fields

- `mae_pts` and `mfe_pts` do not exist in the full chronological OG ledgers
  or selected trigger logs.
- They are computed, not estimated, from raw 1-minute OHLC bars by scanning
  each trade's recorded `entry_time` through recorded `exit_time`, inclusive,
  using `side` to convert high/low movement into favorable and adverse
  point excursion.
- The 2013-2015 raw file is committed but multi-symbol; it must be normalized
  with the same continuous-contract rule documented in `scripts/build_nq_continuous.py`.
- The 2018-2026 continuous bar file is not committed because of size, so
  artifact regeneration requires local data or an explicit path. If that
  source is absent, the builder fails instead of substituting estimates.
- The OG ledgers expose `cap`, not explicit `raw_stop_pts` or
  `effective_stop_pts`; forward artifacts will map both stop fields to `cap`
  and document that there is no separate raw/effective stop distinction in
  these locked OG trade CSVs.

The MAE/MFE limitation is bar resolution, not estimation: 1-minute OHLC does
not contain tick ordering within the entry or exit minute. The fields are
therefore actual 1-minute bar-extrema excursions, with
`mae_mfe_status=computed_from_1m_ohlc_entry_to_exit_inclusive` and
`mae_mfe_resolution=1m_ohlc_bar_extrema`.

## Existing Reusable Modules

- `src.og_regime_killswitch.rolling_pf_killswitch`
- `src.og_regime_killswitch.apply_flat_mask`
- `src.og_regime_killswitch.summarize`
- `src.metrics.profit_factor`
- `src.metrics.max_drawdown`
- `scripts/build_nq_continuous.py`: canonical daily-volume continuous-contract
  rule for multi-contract Databento raw files.

## Proposed Architecture

Add:

- `src/forward_ledger.py`
  - schema validation;
  - gross profit/gross loss/net/PF invariant helpers;
  - raw 1-minute OHLC loaders;
  - canonical 2013-2015 continuous-bar reconstruction;
  - actual per-trade MAE/MFE computation;
  - selected trigger-log merge;
  - normalized 1RR and 1.5R trade-packet builders;
  - complete block-weight and scenario-manifest builders.
- `scripts/build_forward_ledger_artifacts.py`
  - reads committed historical outputs plus required raw/local 1-minute bars;
  - writes `artifacts/forward_ledger/`;
  - fails on missing required source columns;
  - fails on missing required bar paths instead of inventing MAE/MFE values.
- `tests/test_forward_ledger.py`
  - metrics/PF invariants;
  - selected rolling-PF numbers;
  - schema and scenario-manifest invariants.

## Expected Artifacts

Under `artifacts/forward_ledger/`:

- `historical_trade_pool_1rr.csv`
- `historical_trade_pool_1_5rr.csv`
- `forward_source_pool.csv`
- `point_scale_scenarios.json`
- `expectancy_scenarios.json`
- `scenario_manifests.json`
- `scenario_block_weights.csv`
- `forward_ledger_summary.json`
- `README.md`

## Tests To Be Added

- Gross profit, gross loss, net, and PF invariant tests.
- Invariant that positive net points with gross loss > 0 implies PF > 1.
- Selected rolling PF 100/1.10 reproduction tests:
  - `primary_150r`: `PF_R=1.234475`, `avg_R_per_trade=0.051613`,
    `max_dd_R=-14.531`, points-PF `1.448333`.
  - `operational_100r`: `PF_R=1.249115`,
    `avg_R_per_trade=0.045933`, `max_dd_R=-10.969`, points-PF
    `1.568369`.
- Tests that 1RR and 1.5R pools are separate and retain current point
  geometry.
- Tests that actual MAE/MFE are finite, non-negative, bar-count-backed, and
  internally consistent with TP/SL trades.
- Tests that point-scale scenarios and expectancy scenarios are separate.
- Tests that all PF 1.35, 1.50, and 1.65 scenario manifests have complete
  block weights.
- Tests that missing required source columns fail honestly.

## Blockers

- The 2018-2026 continuous 1-minute bar file is not committed. This is a
  blocker for regenerating MAE/MFE unless `data/nq_1m/nq_continuous_2018_2026_1m.csv`
  exists locally or an equivalent path is supplied.
- Tick-level entry/exit-minute ordering is unavailable. This is a precision
  limitation of the source data, not a blocker for 1-minute actual MAE/MFE.

## Pre-Change Reproduction

Verified before implementation:

- Branch: `research/og-regime-killswitch`
- Recent commits:
  - `285734c` assemble full chronological trade sequences
  - `9e6cadc` implement 4 kill-switch mechanisms and 62-variant backtest
  - `12a0f77` add year-by-year baseline-vs-switch table
- Selected row reproduction from committed CSVs:
  - `primary_150r`: `PF_R=1.234475099113488`,
    `avg_R_per_trade=0.0516127464184325`,
    `max_dd_R=-14.531184481261048`,
    `PF_pts=1.44833308257292`
  - `operational_100r`: `PF_R=1.2491153590474051`,
    `avg_R_per_trade=0.0459327904961629`,
    `max_dd_R=-10.96913872102261`,
    `PF_pts=1.568369164695021`
- Baseline rows:
  - `primary_150r`: `PF_R=1.0764739550930975`,
    `PF_pts=1.2781647580792608`
  - `operational_100r`: `PF_R=1.0231108277534768`,
    `PF_pts=1.298998596872805`
- Causality tests:
  - `python3 -m pytest -q tests/test_regime_killswitch_causality.py`
  - result: `4 passed`
