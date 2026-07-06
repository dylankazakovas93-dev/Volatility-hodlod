# OG VXN Mechanism Diagnostic

Phase: `POST_VALIDATION_EXPLORATORY_REDEVELOPMENT`. Source data:
`outputs/og_vxn/{OG_PRIMARY_150R,OG_OPERATIONAL_100R}__NO_VXN_FILTER_trades.csv`
(the unfiltered ledgers for each base -- every physically executed trade,
bucketed by its own `vxn_prev_close` value, independent of which filter
candidate would keep or drop it). Full table:
`outputs/og_vxn/vxn_mechanism_buckets.csv`.

Buckets: `<20`, `20-25`, `25-30`, `>=30` (matching the filter thresholds
tested). No trade in either base's unfiltered ledger fell into
`NO_VXN_AVAILABLE` (every executed trade had a resolvable causal VXN
close under the forward-fill rule).

## Table (both bases pooled: `ALL_BASES`)

| Bucket | n_trades | avg stop cap (pts) | median stop cap | net_pts | total_R | avg R/trade | PF_pts | PF_R |
|---|---|---|---|---|---|---|---|---|
| `<20` | 728 | 44.61 | 33.00 | 1230.10 | 3.01 | 0.0041 | 1.1229 | 1.0114 |
| `20-25` | 572 | 67.47 | 55.13 | 3259.12 | 21.68 | 0.0379 | 1.2498 | 1.1000 |
| `25-30` | 415 | 68.73 | 56.25 | 5415.22 | 36.31 | 0.0875 | 1.7012 | 1.2574 |
| `>=30` | 359 | 90.78 | 75.38 | 2918.17 | 4.37 | 0.0122 | 1.2999 | 1.0336 |

Per-base tables (`OG_PRIMARY_150R`, `OG_OPERATIONAL_100R`) are in
`outputs/og_vxn/vxn_mechanism_buckets.csv` and track the pooled table
closely (both bases share the same touch population; only the target
distance differs).

## Stop-cap-scaling conclusion (explicit, quantitative)

The average original stop cap in the `>=30` bucket is **90.78 points**
versus **44.61 points** in the `<20` bucket -- a **103.5% increase**
(more than double). Median cap shows the same pattern (75.38 vs 33.00,
+128%). This is exactly what the cap formula predicts:
`cap = min(1.5 * anchor, SL_CAP)` scales with the realized 60-minute IB
range (`anchor`), and high-VXN sessions mechanically produce larger
IB ranges.

Meanwhile, **avg R/trade in the `>=30` bucket is 0.0122, versus 0.0041 in
the `<20` bucket** -- a difference of only 0.008 R/trade, i.e. R-normalized
expectancy in the highest-VXN bucket is not meaningfully better than in
the lowest-VXN bucket (both are close to flat/marginal, PF_R 1.03 vs
1.01, both barely above breakeven). Net points, by contrast, differ by
2.4x (2918 vs 1230) between the same two buckets -- **this net-points gap
is consistent with a pure stop-cap-scaling effect**: bigger caps produce
proportionally bigger point swings per trade for a similar underlying R
outcome, not a genuinely bigger per-unit-of-risk edge.

The apparent best bucket by both points and R is `25-30`
(avg R/trade 0.0875, PF_R 1.26) -- noticeably higher than either
neighboring bucket (`20-25`: 0.0379; `>=30`: 0.0122). This is a
**non-monotonic spike**, not a smooth volatility-regime gradient: if
elevated VXN itself carried a real, structural edge, expectancy would be
expected to rise (or at least not fall) monotonically with VXN level;
instead it rises from `<20` to `25-30` and then **falls back down** at
`>=30`. That pattern is more consistent with a specific band of trades in
the historical sample happening to perform well (sampling noise /
selection effect concentrated at one threshold) than with a genuine,
generalizable "high VXN = better edge" mechanism.

**Conclusion:** the raw-point edge visible in the `VXN_PREV_CLOSE_GE_*`
filter family is *substantially* explained by stop-cap scaling with
realized volatility, not by a clean R-normalized expectancy improvement.
The one candidate that does show a genuine (if modest) R-normalized
improvement, `VXN_PREV_CLOSE_GE_25`, sits at a non-monotonic local peak
between two buckets/thresholds (`GE_20`, `GE_30`) that do *not* show the
same improvement and in the pooled former-validation group actually go
*negative* on total R (see `docs/OG_VXN_EXPLORATORY_RESULTS.md` §
Robustness checklist, criterion 8) -- this is the classic signature of a
threshold selected because it happens to isolate a favorable slice of the
existing sample, not because VXN level itself is a robust causal
volatility-regime filter for this strategy's edge.
