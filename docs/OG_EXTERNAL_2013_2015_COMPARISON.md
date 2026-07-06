# OG Historical Context Table (descriptive; groups never pooled)

Four independent evidence groups exist for the OG dual configs. They use
disjoint year sets, disjoint purposes, and are reported side-by-side purely
for orientation -- **never combined into one pooled number**. Two are
reused read-only from prior branches/commits (not recomputed here); one is
this diagnostic.

| group | years | purpose | source (read-only unless noted) |
|---|---|---|---|
| `RETROSPECTIVE_BUILD` | 2018, 2020, 2023, 2026 (partial) | candidate selection / build-off | `outputs/og_build_years/final_buildoff_be45.csv`, `docs/OG_FINAL_BUILDOFF_BE45.md` |
| `LOCKED_VALIDATION` | 2019, 2021, 2022, 2024, 2025 | frozen out-of-sample validation, preregistered gate | `outputs/og_validation/`, `docs/OG_VALIDATION_RESULTS_DUAL_CONFIG.md` (commit `add8f30`) |
| `EXTERNAL_DIAGNOSTIC` (this document) | 2013, 2014, 2015 | descriptive external-data diagnostic, not a validation | `outputs/og_external_2013_2015/` (this task) |
| `PARTIAL_2026_BUILD` | 2026 (partial year, subset of `RETROSPECTIVE_BUILD`'s "Candidate A" row) | same build-off, partial-year caveat | `outputs/og_build_years/final_buildoff_be45.csv` |

## RETROSPECTIVE_BUILD (Candidate B == OG_PRIMARY_150R lineage; Candidate A rows shown, B not separately tabulated in the CSV for 2018/2020/2023/2026 -- see note)

The committed `outputs/og_build_years/final_buildoff_be45.csv` only carries
per-year rows for "Candidate A" (all four build years) in this file; it is
reproduced here verbatim, unmodified:

| candidate | year | trades | net pts | PF pts | PF R | total R | avg R/trade | win rate | max DD pts | max DD R | profitable/losing/BE days |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A | 2018 | 113 | 319.92 | 1.3565 | 1.4245 | 14.3037 | 0.1266 | 0.4248 | -177.38 | -5.6963 | 42/30/18 |
| A | 2020 | 137 | 1345.31 | 1.5744 | 1.0166 | 0.7581 | 0.0055 | 0.3431 | -721.54 | -8.0000 | 43/41/21 |
| A | 2023 | 100 | 494.53 | 1.2872 | 1.3316 | 9.7365 | 0.0974 | 0.4100 | -378.11 | -3.7536 | 38/27/21 |
| A | 2026 (partial year) | 57 | 2533.00 | 3.2937 | 2.6596 | 19.6536 | 0.3448 | 0.5789 | -355.12 | -4.0000 | 31/9/7 |

All four rows are net positive in points, PF points, and total R.

## LOCKED_VALIDATION (`docs/OG_VALIDATION_RESULTS_DUAL_CONFIG.md`, commit `add8f30`, verdict `DUAL_CONFIG_FAIL`)

| config | year | trades | net pts | PF pts | PF R | total R | avg R/trade | win rate |
|---|---|---|---|---|---|---|---|---|
| OG_PRIMARY_150R | 2019 | 124 | -415.82 | 0.7206 | 0.6266 | -22.6113 | -0.1823 | 0.2339 |
| OG_PRIMARY_150R | 2021 | 131 | 941.74 | 1.3782 | 1.3568 | 17.0524 | 0.1302 | 0.3435 |
| OG_PRIMARY_150R | 2022 | 125 | 1303.00 | 1.4338 | 1.1078 | 4.8785 | 0.0390 | 0.2800 |
| OG_PRIMARY_150R | 2024 | 117 | -441.80 | 0.8766 | 0.7680 | -12.9832 | -0.1110 | 0.2650 |
| OG_PRIMARY_150R | 2025 | 133 | 330.29 | 1.0906 | 1.0582 | 2.8139 | 0.0212 | 0.2632 |
| OG_PRIMARY_150R | pooled | 630 | 1717.42 | 1.1209 | 0.9579 | -10.8496 | -0.0172 | 0.2778 |
| OG_OPERATIONAL_100R | 2019 | 124 | -500.01 | 0.6463 | 0.5733 | -24.5150 | -0.1977 | 0.2903 |
| OG_OPERATIONAL_100R | 2021 | 133 | 559.90 | 1.2325 | 1.1157 | 5.4139 | 0.0407 | 0.3985 |
| OG_OPERATIONAL_100R | 2022 | 125 | 1499.88 | 1.5463 | 1.1875 | 7.7375 | 0.0619 | 0.3920 |
| OG_OPERATIONAL_100R | 2024 | 117 | -433.72 | 0.8699 | 0.7687 | -12.0228 | -0.1028 | 0.3504 |
| OG_OPERATIONAL_100R | 2025 | 134 | 687.24 | 1.1981 | 1.1697 | 7.6897 | 0.0574 | 0.3955 |
| OG_OPERATIONAL_100R | pooled | 633 | 1813.28 | 1.1356 | 0.9353 | -15.6968 | -0.0248 | 0.3665 |

Both pooled-total-R figures are negative despite positive pooled net
points -- this is why the locked validation is `DUAL_CONFIG_FAIL` (fails
the preregistered gate on total_R and other criteria in
`docs/OG_VALIDATION_RESULTS_DUAL_CONFIG.md`).

## EXTERNAL_DIAGNOSTIC (2013-2015, this task; full detail in `docs/OG_EXTERNAL_2013_2015_RESULTS.md`)

| config | trades | net pts | PF pts | PF R | total R | avg R/trade | win rate |
|---|---|---|---|---|---|---|---|
| OG_PRIMARY_150R (pooled 2013-2015) | 315 | -45.69 | 0.9690 | 1.0232 | 3.0254 | 0.0096 | 0.3048 |
| OG_OPERATIONAL_100R (pooled 2013-2015) | 315 | -261.61 | 0.8193 | 0.8618 | -17.4414 | -0.0554 | 0.3556 |

Family verdict: `EXTERNAL_DUAL_NO_SUPPORT`.

## Cross-group observation (descriptive only, not a combined statistic)

All three independently-computed groups (build, locked validation,
external diagnostic) show the same qualitative pattern for both configs:
positive-looking net-points figures are not reliably accompanied by
positive pooled total (cap-normalized) R, and year-to-year variance is
large relative to the mean. The 2013-2015 external window adds a third,
fully independent data source (different vendor lineage for both NQ and
VXN than the 2018-2026 canonical archive) showing the same instability,
which is suggestive but --- given only 3 additional years, no shared
preregistration with the locked validation, and a fail-closed but
still-diagnostic-only gate --- is not treated here as decisive corroboration
of `DUAL_CONFIG_FAIL`, only as consistent with it.
