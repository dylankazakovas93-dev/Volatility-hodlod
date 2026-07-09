# ES/VIX Level Discovery & MAE/MFE — Master Plan

## Project objective

Determine whether the genuine volatility-derived level-generation formula creates
high-quality ES mean-reversion first-touch signals when driven by the official
Cboe VIX Index, then determine whether causal information available at touch
time can support interpretable MAE/MFE formulas.

This is **not** a trading-strategy backtest. It is a level-discovery and
excursion-characterisation study.

## Absolute prohibitions

This plan explicitly prohibits adding or optimising:

- stops;
- targets;
- R multiples;
- break-even rules;
- trailing exits;
- position sizing;
- entry blackouts;
- prop-firm rules;
- commissions;
- fees;
- slippage;
- rolling PF gates;
- NQ trade-management rules.

No performance outcomes, rankings, candidate elimination, formula fitting or
holdout opening may occur during Stage 0.

---

## Research sequence

1. Lock causal ES data and official Cboe VIX data.
2. Preregister the finite level grid (132 configurations).
3. Generate levels.
4. Detect independent first physical touches.
5. Calculate unrestricted fixed-horizon MAE/MFE.
6. Eliminate weak level configurations through chronological gates.
7. Select a stable parameter neighbourhood.
8. Freeze one ES/VIX level generator.
9. Build a causal touch-time feature dataset.
10. Fit interpretable MAE/MFE quantile formulas.
11. Validate using purged chronological testing, CPCV, DSR, HAC and block bootstrap.
12. Open one final untouched holdout once.
13. Decide whether full ES configuration research is justified.

---

## Repository and branch

- Repository: `dylankazakovas93-dev/Volatility-hodlod`
- Branch: `research/es-vix-level-mae-mfe-discovery`
- Base commit: `f4a8bad0e9671a026280dba97c6df557a20e0684`

---

## Data

### ES source archives (Databento GLBX.MDP3, ohlcv-1m, ES.FUT parent symbology)

| Archive | Raw CSV file (inside ZIP) | Coverage (UTC) | Rows | Member SHA-256 |
|---|---|---|---|---|
| `es2018.zip` | `glbx-mdp3-20180101-20191231.ohlcv-1m.csv.zst` | 2018-01-01 23:00Z → 2019-12-31 21:59Z | 1,118,868 | `a3f9eaa2...` |
| `es2023.zip` | `glbx-mdp3-20200101-20231230.ohlcv-1m.csv.zst` | 2020-01-01 23:00Z → 2023-12-29 21:59Z | 2,247,980 | `12ddd7a8...` |
| `es2026.zip` | `glbx-mdp3-20240101-20260608.ohlcv-1m.csv.zst` | 2024-01-01 23:00Z → 2026-06-08 23:59Z | 1,375,031 | `1a41db6e...` |

Raw archives live in the canonical data library at `/workspaces/quant-stack/data/raw/ES/`.

### Causal ES continuous one-minute CSV

Built by `scripts/build_es_continuous_causal.py` — uses previous-completed-session
volume dominance, never same-day volume.

- Path: `data/es_1m/es_continuous_causal_2018_2026_1m.csv` (gitignored)
- SHA-256: recorded in `data_manifest.json`
- Row count: recorded in `research/es_vix_level_discovery/data/ES_CAUSAL_DATA_VALIDATION.md`
- First complete ES RTH session: recorded in validation doc
- Last complete ES RTH session: recorded in validation doc

### Official Cboe VIX daily

- Source: `https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv`
- Raw: `data/vix_raw_cboe_official.csv` (committed)
- Normalised: `data/vix_daily_1990_2026.csv` (committed)
- Columns: `date`, `vix_open`, `vix_high`, `vix_low`, `vix_close`
- Span: 1990-01-02 → 2026-07-08

### Causal VIX rule

Session D uses only the latest completed VIX close available strictly before ES
RTH opens at 09:30 America/New_York. Same-session eventual VIX close is
forbidden. Every generated level exposes `vix_source_date` and `vix_available_at`.

---

## Level-generation formula

For ES RTH session D:

### Inputs

```
cash_open = first ES RTH bar open at 09:30 America/New_York
prior_vix_close = most recent completed Cboe VIX close available before ES opens
sigma_multiplier = one of [0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
ib_minutes = one of [30, 60]
offset_family = proportional (offset_pct) or fixed (fixed_offset_es_points)
```

### Sigma day

```
sigma_day = cash_open * (prior_vix_close / 100) / sqrt(252)
```

### Implied volatility levels

```
imp_up = cash_open + sigma_multiplier * sigma_day
imp_dn = cash_open - sigma_multiplier * sigma_day
```

### Initial Balance

```
ib_duration = ib_minutes (30 or 60)
ib_high = highest high during IB
ib_low = lowest low during IB
ib_range = ib_high - ib_low
ib_ext_up = ib_high + ib_range
ib_ext_dn = ib_low - ib_range
```

The level becomes live only after IB completion. The creation bar (the bar at
which the level is first available) cannot count as a touch.

### Offset

For proportional offsets (offset_pct ∈ [0.00, 0.02, 0.04, 0.06, 0.08, 0.10]):

```
sigma_offset = sigma_day * offset_pct
```

For fixed offsets (fixed_offset_es_points ∈ [2.5, 5.0, 7.5, 10.0, 15.0]):

```
sigma_offset = fixed_offset_es_points
```

### Final levels

```
upper_level = (ib_ext_up + imp_up) / 2 - sigma_offset
lower_level = (ib_ext_dn + imp_dn) / 2 + sigma_offset
```

### Direction hypothesis

- Upper-level first physical touch = SHORT observation
- Lower-level first physical touch = LONG observation

### Fixed mechanics

- 20 eligible-session lifetime
- Creation bar excluded
- First physical touch only (each level consumed permanently on its first touch)
- Deterministic simultaneous-touch ordering (older level first, upper before lower)
- Genuine expiry convention
- Each level is an independent observation
- No one-global-position rule
- No overlap blocking
- No stacking rule

Overlapping future label windows receive `overlap_cluster_id` values for
dependence handling.

---

## Future MAE/MFE label contract

MAE and MFE are **nonnegative** magnitudes applied to the first touch of each
level. Primary labels begin on the first complete one-minute bar **after** the
touch bar.

### Horizons

- 15 minutes
- 30 minutes
- 60 minutes
- 120 minutes
- Remainder of ES RTH

### Formulas

For LONG:

```
MFE = future maximum high - reference_entry_price
MAE = reference_entry_price - future minimum low
```

For SHORT:

```
MFE = reference_entry_price - future minimum low
MAE = future maximum high - reference_entry_price
```

### Reference entry price

Clean touch:

```
reference_entry_price = level_price
gap_through = false
```

Gap-through touch:

```
reference_entry_price = touch_bar_open
gap_through = true
```

### Prohibitions

- Do not use the touch bar's eventual high or low in primary labels
- Do not censor labels at any stop, target, BE rule or strategy exit
- Do not calculate labels during Stage 0

---

## Preregistered grid (132 configurations)

| Parameter | Values | Count |
|---|---|---|
| `sigma_multiplier` | 0.75, 1.00, 1.25, 1.50, 1.75, 2.00 | 6 |
| `ib_minutes` | 30, 60 | 2 |
| `offset_family` | proportional (offset_pct) or fixed (fixed_offset_es_points) | 2 |
| Offset A — proportional | 0.00, 0.02, 0.04, 0.06, 0.08, 0.10 | 6 |
| Offset B — fixed (ES points) | 2.5, 5.0, 7.5, 10.0, 15.0 | 5 |
| `line_life_sessions` | 20 (fixed) | 1 |

Total: 6 × 2 × (6 + 5) = 132

No other parameters vary.

---

## Holdout firewall

- **Development period:** 2018-01-01 → 2024-12-31 (inclusive start)
- **Final untouched holdout:** 2025-01-01 through the final complete ES RTH session
- The holdout is **one indivisible block**
- There is **no candidate-review or validation split within 2025**
- The holdout **must not** be used for: grid ranking, candidate elimination,
  horizon selection, baseline selection, parameter selection, feature selection,
  formula selection, coefficient fitting, transformations, thresholds, or
  outcome-driven debugging
- Status: `UNOPENED`
- `outcome_columns_read`: `false`

---

## Chronological research periods

No gate may be entered during Stage 0.

| Period | Purpose |
|---|---|
| 2018–2019 | Development |
| Gate A | 2020 |
| Through 2021 | Expanded development |
| Gate B | 2022 |
| Through 2023 | Expanded development |
| Gate C | 2024 |
| 2025 → end | Final untouched holdout |

No new parameter values may be added after a gate is opened. Eliminated
configurations remain eliminated.

### Selection criteria (future application)

- Touch count
- Median MFE
- Median MAE
- MAE tail quantiles
- MFE/MAE relationship
- Favourable-before-adverse first passage
- Matched-random baseline lift
- Long/short stability
- Year stability
- VIX-regime stability
- Time-of-day stability
- Neighbouring-parameter support
- Overlap-adjusted effective sample size

Do **not** maximise raw MFE alone.

### Validation methods (future application)

After freezing a level configuration, formula validation may use:

- Purged chronological testing
- CPCV as robustness evidence
- DSR with complete trial accounting
- HAC / Newey-West
- Chronological block bootstrap
- Brown-Forsythe or Levene tests
- Final untouched holdout once

---

## Files and directory layout

```
research/es_vix_level_discovery/
├── MASTER_PLAN.md              ← this file
├── PROGRESS.md                 ← session progress (crash-safe)
├── DECISIONS.md                ← Material decisions and rationale
├── HOLDOUT_LOCK.json           ← Holdout firewall
├── GRID_DEFINITION.json        ← Preregistered 132-config grid
├── TRIAL_REGISTRY.csv          ← Append-only trial registry
├── data_manifest.json          ← File hashes and provenance
├── data/
│   ├── ES_CAUSAL_ROLL_SCHEDULE.csv    ← Deterministic roll schedule
│   └── ES_CAUSAL_DATA_VALIDATION.md   ← ES continuous data validation
└── runs/                              ← Future experiment runs
    └── <run-id>/
        ├── MANIFEST.json
        ├── metrics.json
        ├── REPORT.md
        └── output_hashes.txt
```

## Crash-safe rules

1. Commit and push each stage before beginning the next.
2. Keep PROGRESS.md current before each long operation.
3. Raw data remains gitignored. Derived artifacts, configs, tests, manifests
   and hashes are committed.
4. Never leave formulas, findings, or decisions only in chat.

---

## New-session opening prompt

Copy everything below into OpenCode at the start of Stage 1 after giving it
access to this repository and master plan file.

```
Read `research/es_vix_level_discovery/MASTER_PLAN.md` completely before taking
action. Treat it as the controlling specification.

Repository: dylankazakovas93-dev/Volatility-hodlod
Branch: research/es-vix-level-mae-mfe-discovery

This is a level-discovery and excursion-characterisation study, not a
trading-strategy backtest.

Do not add stops, targets, R multiples, break-even rules, trailing exits,
position sizing, entry blackouts, prop-firm rules, commissions, fees, slippage,
rolling PF gates, or NQ trade-management rules.

Begin with Stage 1 only. Do not skip ahead.
```