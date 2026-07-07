# Rolling-PF Kill-Switch — Year-by-Year Table (Baseline vs. With-Switch)

Selected mechanism: **rolling points-PF, trailing 100 trades, threshold 1.10,
symmetric re-entry** — go flat whenever trailing-100-trade points-PF drops
below 1.10, resume once it recovers above 1.10. Selected in
`docs/OG_REGIME_KILLSWITCH_RESULTS.md` as the best of 62 backtested variants
(4 mechanism families x parameter grids x 2 configs) by PF_R.

**Caveat, repeated from the original study and still fully in force:** this
threshold was chosen with full knowledge of which years were historically bad
(2014, 2015, 2019, 2024) and picked as the best cell from a small
preregistered grid. It is a retrospective fit on already-viewed data, not a
freshly validated rule tested on unseen data. Treat this table as "how well
would this specific rule have worked, in hindsight" — not as evidence it will
work on the next bad year.

Source data: `outputs/og_regime_killswitch/{primary_150r,operational_100r}_full_chronological_trades.csv`
merged against `outputs/og_regime_killswitch/{primary_150r,operational_100r}_trigger_log_rolling_pf_w100_t1.1_symmetric.csv`
on `entry_time`. Points-PF only (not R-normalized) throughout this table —
see `docs/OG_REGIME_KILLSWITCH_RESULTS.md` for the R-normalized (PF_R)
comparison that drove the original selection.

## OG_PRIMARY_150R (target 1.50R)

| Year | Baseline n | Baseline net_pts | Baseline PF | With-switch n | With-switch net_pts | With-switch PF |
|---|---|---|---|---|---|---|
| 2013 | 86 | +115.21 | 1.484 | 86 | +115.21 | 1.484 |
| 2014 | 109 | -104.86 | 0.793 | 47 | -71.92 | 0.648 |
| 2015 | 120 | -56.04 | 0.923 | **0** | **0.00** | — (fully avoided) |
| 2018 | 113 | +620.93 | 1.676 | 100 | +520.99 | 1.617 |
| 2019 | 124 | -415.82 | 0.721 | 60 | **-122.60** | 0.824 |
| 2020 | 137 | +1401.01 | 1.545 | 109 | +888.47 | 1.396 |
| 2021 | 131 | +941.74 | 1.378 | 131 | +941.74 | 1.378 |
| 2022 | 125 | +1303.00 | 1.434 | 124 | +1331.88 | 1.448 |
| 2023 | 99 | +645.14 | 1.363 | 94 | +643.64 | 1.378 |
| 2024 | 117 | -441.80 | 0.877 | 21 | -99.96 | 0.753 |
| 2025 | 133 | +330.29 | 1.091 | 19 | +405.94 | 2.209 |
| 2026 (partial) | 55 | +1932.07 | 2.211 | 46 | +1451.51 | 2.155 |
| **ALL (pooled)** | **1349** | **+6270.87** | **1.278** | **837** | **+6004.89** | **1.448** |

## OG_OPERATIONAL_100R (target 1.00R)

| Year | Baseline n | Baseline net_pts | Baseline PF | With-switch n | With-switch net_pts | With-switch PF |
|---|---|---|---|---|---|---|
| 2013 | 86 | +57.21 | 1.254 | 86 | +57.21 | 1.254 |
| 2014 | 109 | -182.41 | 0.638 | 20 | -32.43 | 0.593 |
| 2015 | 120 | -136.41 | 0.810 | **0** | **0.00** | — (fully avoided) |
| 2018 | 113 | +319.92 | 1.357 | 94 | +176.30 | 1.216 |
| 2019 | 124 | -500.01 | 0.646 | 43 | **-16.38** | 0.965 |
| 2020 | 137 | +1345.31 | 1.574 | 106 | +880.68 | 1.436 |
| 2021 | 133 | +559.90 | 1.232 | 107 | +486.87 | 1.244 |
| 2022 | 125 | +1499.88 | 1.546 | 121 | +1544.13 | 1.592 |
| 2023 | 100 | +494.53 | 1.287 | 100 | +494.53 | 1.287 |
| 2024 | 117 | -433.72 | 0.870 | 26 | -140.46 | 0.739 |
| 2025 | 134 | +687.24 | 1.198 | 20 | +754.75 | 3.655 |
| 2026 (partial) | 57 | +2533.00 | 3.294 | 57 | +2533.00 | 3.294 |
| **ALL (pooled)** | **1355** | **+6244.43** | **1.299** | **780** | **+6738.19** | **1.568** |

## Reading this table

- Pooled points-PF improves for both configs with the switch applied:
  1.278 -> 1.448 (150R), 1.299 -> 1.568 (100R). The earlier "1.29" figure
  quoted in conversation is the pooled **baseline** PF (no switch) — the
  switched PF is meaningfully higher, not a plateau at 1.29.
- 2015 is fully avoided (0 trades survive the filter) in both configs.
- 2019's loss is cut from -415.82/-500.01 to -122.60/-16.38 (roughly
  70-97% of the loss removed).
- 2024's loss is cut from -441.80/-433.72 to -99.96/-140.46 (roughly
  68-78% removed), but not eliminated — the switch mostly sits out 2024
  (only 21/117 and 26/117 trades survive) rather than fully avoiding it,
  and the residual trades it does let through in 2024 are still weak
  (PF 0.753/0.739 on the surviving trades).
- 2013/2021/2023 are essentially untouched (little to no filtering) —
  the switch correctly stays out of the way during already-good stretches.
- Net points fall slightly for PRIMARY_150R (6270.87 -> 6004.89, since some
  good trades are also filtered out during flat periods) but rise for
  OPERATIONAL_100R (6244.43 -> 6738.19). PF improves in both regardless of
  the net-points direction, since fewer, higher-quality trades survive.

See `docs/OG_REGIME_KILLSWITCH_MECHANISMS.md` for how the mechanism works
and `docs/OG_REGIME_KILLSWITCH_RESULTS.md` for the full 62-variant comparison
and PF_R-based selection rationale.
