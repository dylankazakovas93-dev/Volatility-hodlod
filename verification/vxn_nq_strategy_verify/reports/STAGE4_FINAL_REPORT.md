# Stage 4 Final Report — OG_OPERATIONAL_100R Pooled/Gated Reproduction

## Completed Operations
- Assembled 1,355 shadow rows from 3 frozen component ledgers
- Applied independent rolling PF gate (w=100, t=1.10, symmetric)

## Provenance by Source
| Source | Rows | Years |
|---|---|---|
| external_2013_2015 | 315 | 2013-2015 |
| build_years | 407 | 2018, 2020, 2023, 2026 |
| validation | 633 | 2019, 2021-2022, 2024-2025 |

## Rolling-PF Gate
- Window: 100 prior shadow trades
- Threshold: 1.10 symmetric
- Current row excluded from own PF calculation
- OFF rows remain in shadow and influence future windows

## Metrics
| Metric | Expected | Actual | Match |
|---|---|---|---|
| Shadow rows | 1,355 | 1,355 | ✓ |
| ON rows | 780 | 780 | ✓ |
| OFF/flat rows | 575 | 575 | ✓ |
| Flat runs | 20 | 20 | ✓ |
| Effective net points | 6,738.191 | 6,738.191 | ✓ |
| Points PF | 1.568369 | 1.568369 | ✓ |
| Total R | 62.2389 | 62.2389 | ✓ |
| R PF | 1.249115 | 1.249115 | ✓ |
| MDD points | -721.5375 | -721.5375 | ✓ |
| MDD R | -10.9691 | -10.9691 | ✓ |

## Reconciliation
- is_flat mismatches: 0 across all 1,355 rows

## Determinism
- Identical on second independent run (hash verified)

## Causality Tests
- prefix_invariance: ✓
- append_invariance: ✓
- current_row_excluded: ✓
- future_row_excluded: ✓
- warmup_100_on: ✓
- zero_loss_denominator: ✓
- symmetric_110_behavior: ✓
- off_rows_influence_future: ✓
- deterministic_output: ✓

## Verdict
EXACT_REPRODUCTION

## Tests
98/98 passed (72 Stage 1 + 13 Stage 2 + 13 Stage 4/causality)
