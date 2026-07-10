# Matched-Random Baseline Definitions

## Purpose

For every physical first touch, generate matched random ES entry timestamps
from the development period (2018–2019) to create a counterfactual
distribution. The actual configuration's excursion metrics are compared
against this distribution to calculate baseline lift.

## Matching Dimensions

Every random observation must match the actual touch on:

| Dimension | Source | Notes |
|---|---|---|
| Calendar year | touch timestamp | Exact match |
| Calendar month | touch timestamp | Exact match where possible |
| Weekday | touch timestamp | 0=Monday through 4=Friday |
| RTH time bucket | touch timestamp | 30-minute buckets: 09:30, 10:00, ..., 15:30 |
| Signal direction | touch_direction | LONG or SHORT |
| VIX decile | vix_close on touch session | Boundaries from 2018–2019 only |
| Roll-day status | roll_day column | 0 or 1 |
| Horizon availability | sufficient bars remain | Must have COMPLETE label for requested horizon |

## VIX Decile Calculation

VIX decile boundaries are computed using all VIX daily closes from
2018-01-01 through 2019-12-31 only.

Decile 1 = lowest 10%, Decile 10 = highest 10%.

Boundaries are frozen once computed and stored in the manifest.

## Resampling

- 1,000 deterministic resamples per configuration per horizon.
- Master seed: `20260709_STAGE2_BASELINE`
- Each of the 1,000 resamples uses seed = `hash(seed_base + "_" + str(resample_i))`
  modulo 2^32.
- All seeds stored in `MANIFEST.json`.

## Sampling Pool

The pool of eligible random timestamps is built from all 2018–2019 ES RTH
bars, excluding the actual touch bar itself and its label window.

## Formulas

Random observations use the identical reference-entry convention, horizon
contract, and MAE/MFE formulas as actual touches.

## Prohibitions

- No sampling from 2020 or later.
- No sampling from bars whose label window is incomplete for the requested
  horizon.
- A random timestamp may not use its own label data within the actual touch's
  label window.

## Baseline Lift Calculation

```
baseline_lift_metric = (actual_metric - median_random_metric) / median_random_metric
```

Calculated for each primary metric at each horizon.

Standard error of the random distribution is recorded for significance
assessment.
