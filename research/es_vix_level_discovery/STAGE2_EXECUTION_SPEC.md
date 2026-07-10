# Stage 2 — Development Grid Execution Specification

## 1. Development Period Firewall

Stage 2 development outcomes may use only bars and touch timestamps within:

**2018-01-01 through 2019-12-31** (inclusive at session-date granularity).

Any input bar, touch timestamp, excursion label bar, or baseline outcome
outside this range must cause non-zero exit.

**Gate A** (2020-01-01 through 2020-12-31) remains unopened.

All later periods (2021 through the final untouched holdout) remain unopened.

## 2. Grid Contract

The exact 132 configurations from `GRID_DEFINITION.json` and
`TRIAL_REGISTRY.csv` are loaded and verified but never altered.

Preflight must prove:
- exactly 132 configurations;
- all config IDs unique;
- every registry row matches one grid row;
- `sigma_multiplier` values exact;
- `ib_minutes` values exact;
- proportional offsets exact;
- fixed offsets exact;
- `line_life_sessions` fixed at 20;
- no stop, target, BE, cost or management fields.

The trial registry is append-only and retains all configurations permanently.

## 3. Primary and Secondary Horizons

**Primary selection horizons:**
- 60 minutes
- 120 minutes

**Secondary diagnostics only (not used for elimination):**
- 15 minutes
- 30 minutes
- RTH_REMAINDER

60-minute and 120-minute results remain separate throughout ranking and
reporting. No winner is selected by whichever horizon later looks best.

Incomplete labels are excluded from that horizon's metric denominator but
remain counted and reported in `incomplete_label_count`.

## 4. Locked Metrics

For every configuration and horizon:

### Counts
- `generated_levels`
- `physical_first_touches`
- `valid_complete_labels`
- `incomplete_labels`
- `long_count`
- `short_count`
- `gap_through_count`
- `ambiguous_first_passage_count`
- `unique_sessions`
- `overlap_clusters`
- `overlap_adjusted_effective_n`

### Excursion Metrics
- `median_mfe_points`
- `median_mae_points`
- `median_mfe_over_sigma_day`
- `median_mae_over_sigma_day`
- `median_mfe_over_ib_range`
- `median_mae_over_ib_range`
- `p75_mfe_over_sigma_day`
- `p90_mfe_over_sigma_day`
- `p75_mae_over_sigma_day`
- `p90_mae_over_sigma_day`
- `p95_mae_over_sigma_day`

### Return Metrics
- `mean_directional_return_over_sigma`
- `median_directional_return_over_sigma`
- `positive_directional_return_rate`

### First-Passage Metrics
For each threshold `t` in {0.25, 0.50, 0.75, 1.00}:
- `p_favorable_first_t`
- `p_adverse_first_t`
- `p_ambiguous_t`
- `p_neither_reached_t`

Denominator for first-passage: all COMPLETE labels for that horizon.

### Stability Diagnostics
- `result_2018` — metric value computed using only 2018 touches
- `result_2019` — metric value computed using only 2019 touches
- `result_long` — metric value computed using only LONG touches
- `result_short` — metric value computed using only SHORT touches
- Monthly distribution of touches
- VIX-regime distribution (VIX deciles)
- Time-of-day distribution (30-min RTH buckets)
- Offset-family distribution
- Neighbouring-parameter support
- Concentration by best 5% of sessions
- Concentration by best month

### Denominator Rules

- **Excursion metrics**: Only COMPLETE labels for the given horizon.
- **Directional return**: Only COMPLETE labels with non-null return.
- **First-passage**: Only COMPLETE labels for the given horizon.
- **LONG/SHORT counts**: All physical touches, independent of label status.
- **Gap-through**: All physical touches with gap_through=true.
- **Invalid denominators**: If MAE denominator would be zero, do not calculate
  a per-trade MFE/MAE ratio. For aggregate comparisons, report:
  `median_mfe_points / median_mae_points` and label exactly as "ratio of medians".

## 5. Matched-Random Baseline

For every actual touch, create matched random ES timestamps using only
development-period data.

Match on:
- calendar year
- calendar month where possible
- weekday
- 30-minute RTH time bucket
- signal direction
- VIX decile
- roll-day status
- availability of the required future horizon

VIX decile boundaries calculated using 2018–2019 development data only.

Use 1,000 deterministic baseline resamples. Store all seeds in a manifest.

Random observations use same reference-entry convention, horizon contract and
MAE/MFE formulas as actual touches.

A random timestamp may not use a bar whose label window is incomplete for the
requested horizon.

## 6. Minimum Power Rules

Eligible for survivor consideration only when:
- at least 100 complete primary-horizon touches total
- at least 30 LONG touches
- at least 30 SHORT touches
- at least 40 unique sessions
- adequate data in both 2018 and 2019

Otherwise classify as **INCONCLUSIVE_LOW_POWER**.

Low-power configs are not classified as PASS.

## 7. Output Artifacts

```
runs/<run_id>/
├── MANIFEST.json
├── CONFIG_RESULTS.csv
├── YEAR_RESULTS.csv
├── DIRECTION_RESULTS.csv
├── MONTH_RESULTS.csv
├── VIX_REGIME_RESULTS.csv
├── TIME_OF_DAY_RESULTS.csv
├── BASELINE_RESULTS.csv
├── NEIGHBOURHOOD_RESULTS.csv
├── SURVIVOR_DECISIONS.csv
├── REPORT.md
└── OUTPUT_HASHES.sha256
```

## 8. Date Firewall Enforcement

The runner must fail nonzero if any of the following fall outside 2018–2019:
- Input bar timestamp used for level generation
- Touch bar timestamp
- Excursion label bar timestamp
- Baseline random-sampling pool timestamp

Exit code 75 on firewall violation.
