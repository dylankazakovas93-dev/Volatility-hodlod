# ES/VIX Level Discovery & MAE/MFE — Progress

## Stage 0 — Evidence Lock (first attempt — rejected by audit)❌

Commit `00711afa567a75a549dd11069a2b42297b377cf3` was rejected by direct
research audit because it used an incomplete specification, a future-aware
noncausal ES builder, and an incorrect holdout firewall.

The prior commit is preserved in history but is not the valid evidence lock.

## Stage 0 — Corrected Evidence Lock ✅

- [x] Complete standalone MASTER_PLAN.md written (level discovery only, no
      trade management, full formula, MAE/MFE contract, chronological gates)
- [x] Corrected branch: `research/es-vix-level-mae-mfe-discovery`
- [x] Official Cboe VIX acquired and validated: 9,224 daily rows, 1990–2026,
      0 duplicates, 0 nulls
- [x] Causal ES continuous builder implemented: `build_es_continuous_causal.py`
      uses prior-session volume dominance, never same-day volume
- [x] Causal ES continuous 1m CSV: 2,804,976 rows, 34 contracts, 33 roll days
- [x] Causal roll schedule: 33 clean quarterly rolls, Good Friday gap handled
- [x] Corrected GRID_DEFINITION.json: 6 sigma × 2 IB × 11 offset = 132 configs
- [x] Corrected TRIAL_REGISTRY.csv: 132 deterministic config IDs, all registered
- [x] Corrected HOLDOUT_LOCK.json: 2025-01-01 to end, one indivisible block,
      UNOPENED, outcome_columns_read=false
- [x] No stop, target, BE, blackout, or strategy-management fields anywhere
- [x] data_manifest.json with outer ZIP SHA-256, causal ES hash, all hashes
- [x] 43 Stage 0 corrected tests all passing
- [x] No performance outcomes generated, no runs directory
- [x] No 2025–2026 OHLC values inspected for strategy purposes
- [x] No level grid executed
- [x] Frozen NQ/VXN branch untouched

## Stage 1 — Level Generation, Touch Detection & MAE/MFE Engine ✅

### Original implementation ❌

Commit `6a71eb20467331a8dded228468d1bffa1f3415f7` contained the following
correction-required issues:

- IB selection used `session_bars.iloc[:ib_minutes]` (row-count) instead of
  actual America/New_York timestamps, creating ambiguous IB boundaries
- Gap-through classification used the completed bar's low/high instead of
  the bar's open to determine whether the market opened through the level
- Line lifetime was hardcoded as 20 in touch detection instead of using
  `config.line_life_sessions`
- Fixed horizons could accumulate bars across multiple sessions
- RTH_REMAINDER could include bars from later trading sessions
- First-passage labels tested at the entry price instead of at the correct
  0.25/0.50/0.75/1.00 × sigma_day threshold levels
- Overlap clusters used an arbitrary `touch_time + 24 hours` window instead
  of the actual label interval extending through the same-session RTH close
- Missing output fields: `first_eligible_at`, `expiry_session`,
  `line_life_sessions`, `source_contract`, `roll_day`, `deterministic_order`,
  `label_status`, required/actual bar counts, sigma-scaled ratios, etc.
- Feature provenance schema was incomplete (missing causality fields,
  formula definitions, and data sources)

### Corrected implementation ✅ (current commit)

- [x] IB selection by timestamp (09:30–10:00 for 30-min, 09:30–10:30 for 60-min)
- [x] 10:00 and 10:30 inclusion verified; creation bar is the IB cutoff bar
- [x] `first_eligible_at` = next complete one-minute bar after creation
- [x] Missing boundary data marks session unavailable with a reason
- [x] Gap-through classification uses `touch_bar_open > level_price` (UPPER)
      or `touch_bar_open < level_price` (LOWER) exclusively
- [x] Gap bar that crosses back through the level remains gap-through
- [x] `config.line_life_sessions` drives touch detection (not hardcoded 20)
- [x] `expiry_session` recorded on every level
- [x] Deterministic ordering: oldest `created_at`, upper before lower,
      `level_id` as final tie-break; `deterministic_order` field populated
- [x] Fixed horizons (15, 30, 60, 120 min) use only same-session RTH bars
- [x] Incomplete horizon: `label_status = INCOMPLETE`, null MAE/MFE,
      `required_bar_count` and `actual_bar_count` recorded
- [x] No overnight carry for fixed horizons
- [x] RTH_REMAINDER uses only the touch session's remaining RTH bars
- [x] RTH_REMAINDER incomplete when no post-touch bar remains
- [x] First-passage at sigma thresholds: 0.25/0.50/0.75/1.00 × sigma_day
- [x] AMBIGUOUS when both favorable and adverse thresholds hit on same bar
- [x] First-passage statuses recorded as fp_025_sigma through fp_100_sigma
      with matching timestamps
- [x] Overlap clusters based on [touch_time+1m, session RTH close] intervals
- [x] Transitive overlap within same session; IDs start at 1
- [x] Cross-session reset; input-order invariant
- [x] Output schema includes all required fields per correction #8
- [x] FEATURE_PROVENANCE.csv with exact_formula, source_data, causality all
      13 required causal columns
- [x] Writers fail loudly on missing required columns
- [x] Repeated CSV generation produces byte-identical output
- [x] No performance outcomes generated, no full 132-grid search run
- [x] No 2025–2026 OHLC values inspected
- [x] Holdout remains UNOPENED, outcome_columns_read remains false

## Stage 2 — Development Execution Framework Frozen ✅

### Stage 2A — Freeze and Build the Grid Runner ✅

- [x] STAGE2_EXECUTION_SPEC.md written: development period locked to 2018–2019
- [x] STAGE2_SELECTION_RULES.json: Pareto-frontier elimination, survivor cap 36
- [x] BASELINE_DEFINITIONS.md: matched-random baseline matching contract frozen
- [x] stage2_runner.py: CLI with --preflight, --synthetic-smoke, --development-run
- [x] stage2_metrics.py: locked metric families (counts, excursions, returns,
      first-passage, stability diagnostics, neighbour support, concentration)
- [x] stage2_baselines.py: 1,000-resample deterministic matched-random baseline
      with VIX deciles from 2018–2019 only, seed manifest
- [x] stage2_selection.py: minimum-power rules, Pareto-frontier dominance,
      isolated-spike detection, direction/year clustering, survivor cap 36
- [x] __init__.py added to research/ and research/es_vix_level_discovery/ for
      consistent import support
- [x] Date firewall enforced: exit code 75 on 2020+ data
- [x] Exactly 132 configurations verified; registry/grid equality enforced
- [x] All metric denominators and missing-value rules defined explicitly
- [x] Ratio of medians (median_MFE / median_MAE) calculated as specified
- [x] VIX deciles from development data only (2018–2019)
- [x] Baseline matching respects horizon availability
- [x] Overlap-adjusted effective sample size computed
- [x] Zero-denominator handling for MAE
- [x] Tests: 69 Stage 2 tests, all passing
- [x] Stage 0 and Stage 1 tests continue to pass (86 + 69 = 155 total)
- [x] --preflight passes
- [x] --synthetic-smoke passes
- [x] --development-run NOT executed
- [x] No 2020+ OHLC or outcome values accessed
- [x] No 2025–2026 OHLC values inspected for any purpose
- [x] Gate A and holdout remain UNOPENED
- [x] Runners directory structure frozen: runs/&lt;run_id&gt;/ with 11 artifact files
- [x] 132-config grid unchanged
- [x] Stage 1 signal/label semantics unchanged
- [x] No TP, SL, BE, trailing, sizing, costs or trade management added

### Stage 2B — Historical Development Results — Not Started
