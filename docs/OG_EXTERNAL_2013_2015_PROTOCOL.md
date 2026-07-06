# OG External 2013-2015 Diagnostic Protocol

Phase label: `POST_VALIDATION_EXTERNAL_DIAGNOSTIC_2013_2015`

This document specifies `scripts/og_external_2013_2015_dual_config.py`
(Step 4) BEFORE any strategy outcome for 2013-2015 has been computed. As of
the commit that introduces this document, no `outputs/og_external_2013_2015/`
ledger, metric, or gate result exists yet.

## Purpose

Run the frozen, unmodified OG dual-config mechanics (`src/strict_engine.py`,
`src/level_generation.py`, `src/og_management_variants.py`,
`src/og_build_variant_engine.py`) against the externally-sourced 2013-2015
NQ archive (`data/external_2013_2015/normalized/nq_continuous_2013_2015_1m.csv`,
sha256 `026aab199422298cfac7d03b1c58e883b74598d3bd0c66cb52cf6b3d2f5ce4da`) and
the officially-sourced Cboe VXN slice
(`data/external_2013_2015/normalized/vxn_daily_2012warmup_2015.csv`, sha256
`9355c3d720ef33707810638e158e513dc1fb037ad77a74bc3a6bfd27664a37c7`), as a
purely descriptive, diagnostic-only exercise. This is neither a retrospective
build-year run nor the locked validation run; it does not reverse or amend
`docs/OG_VALIDATION_RESULTS_DUAL_CONFIG.md` (`DUAL_CONFIG_FAIL`, commit
`add8f30`).

## Design (mirrors scripts/og_validation_dual_config.py)

- Loads both frozen configs and asserts their only difference is
  `target.target_r` (1.50 for `OG_PRIMARY_150R`, 1.00 for
  `OG_OPERATIONAL_100R`); all other effective parameters
  (`level_generation`, `stop_calc`, `one_global_position`, `no_overlap`,
  `no_stacking`, `no_same_minute_reentry`, `permanent_touch_consumption`,
  `tie_order`, `intrabar_ambiguity`, `forced_liquidation_time_et`,
  `prop_hard_blackout`, `entry_blackout`, `sal_enabled`, `management`,
  `hmm_gate`) must be byte-identical between the two configs.
- Bars/VXN file paths are supplied as explicit `--bars`/`--vxn` CLI
  arguments and loaded directly with the existing, unmodified
  `src/data_loader.py::load_1m_ohlcv` / `load_gvz_daily` -- the committed
  config YAML files are read only for their non-data fields (management,
  blackout windows, target_r, etc.) and are never mutated on disk. Both
  supplied files are sha256-checked against the values recorded in
  `docs/OG_EXTERNAL_2013_2015_DATA_REPORT.md` before any engine call.
- Levels are generated with the same `src/level_generation.py::generate_levels`
  / `NQ_PARAMS` used everywhere else in this research line -- no new
  eligibility rule is written. A session only produces a level if
  `generate_levels`'s existing `prior_session_close(vol_close, session_date)`
  lookup succeeds (this is exactly the mechanic that produced the original
  blocker, now satisfied by the 2012-warmup VXN rows) and the existing
  1-hour IB anchor / `LINE_DAYS=20` level-lifetime mechanics in
  `src/strict_engine.py` are otherwise untouched.
- Touches, execution, and management (BE-45, barcount mode, `sal_enabled`
  false, `hmm_gate` none, `tie_order` "age", one global position, no
  overlap, permanent touch consumption, entry blackout 10:00-15:00 ET,
  forced liquidation 15:00 ET, hard blackout 16:00-19:00 ET) run through
  the same `run_variant_managed` used by the locked-validation runner.
- `--years` must be exactly `{2013, 2014, 2015}`. The 2012 rows present in
  the VXN file exist purely as a causal warmup lookup; the runner asserts
  (fail-closed) that no trade with `year == 2012` is ever produced, and
  filters the executed-trade dataframe to the requested year set before any
  metric is computed.
- The first eligible traded date is read directly off the produced ledger
  (`min(session_date)` of `OG_PRIMARY_150R`'s executed trades) rather than
  re-derived with new logic -- both configs share identical eligibility
  mechanics (`target_r` only changes the take-profit distance, not whether
  a session/touch is eligible).
- Separate per-config ledgers are written to `outputs/og_external_2013_2015/`
  (`primary_150r_trades.csv`, `operational_100r_trades.csv`).
- A deterministic-rerun check is performed manually (Step 6): the exact
  same command is run twice and the two ledger sets are byte-diffed.

## Fixed external-support gate (13 criteria, applied independently per config)

1. All invariants pass (config-diff, hash, year-set, PROP_HARD_BLACKOUT,
   no-2012-leak assertions all raise `ExternalDiagFailClosed` otherwise).
2. Deterministic rerun byte-identical.
3. Pooled net points positive.
4. Pooled total cap-normalized R positive.
5. Pooled PF (points) >= 1.10.
6. Pooled PF (R) > 1.00.
7. Average R/trade positive.
8. At least 2 of 3 years (2013/2014/2015) positive in total R.
9. At least 2 of 3 years have PF (points) > 1.00.
10. Pooled total R remains positive excluding the single best year.
11. At least 150 eligible trades after warmup.
12. No single year supplies over 80% of pooled positive net points.
13. Pooled result is not entirely supplied by one isolated month (the best
    positive calendar month's share of total positive monthly net points
    must be < 100%).

`EXTERNAL_SUPPORT` if all 13 hold for a given config, else
`NO_EXTERNAL_SUPPORT`. Family label is one of `EXTERNAL_DUAL_SUPPORT`,
`EXTERNAL_PRIMARY_ONLY_SUPPORT`, `EXTERNAL_OPERATIONAL_ONLY_SUPPORT`,
`EXTERNAL_DUAL_NO_SUPPORT` -- no marginal category. This gate is diagnostic
only; it cannot and does not reverse the locked-validation
`DUAL_CONFIG_FAIL` verdict.

## Tests

`tests/test_og_external_2013_2015_dual_config.py` covers: rejecting
non-`{2013,2014,2015}` year sets (including build years and 2016/2017),
requiring exactly two `--config` arguments, failing closed on a missing or
hash-mismatched `--bars` file, and the `EXTERNAL_YEARS`/`WARMUP_ONLY_YEARS`
constants themselves. These are structural/argument-validation tests only
-- no strategy-outcome number is asserted or has been computed as of this
commit.
