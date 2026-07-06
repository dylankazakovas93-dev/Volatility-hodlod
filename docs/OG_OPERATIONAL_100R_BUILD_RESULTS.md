# OG_OPERATIONAL_100R Build Results (Candidate A, BE45, target 1.00R)

Status: `SECONDARY_OPERATIONAL_CONFIG__RETROSPECTIVE_BUILD_PASS__NOT_VALIDATED`.
Config: `configs/OG_OPERATIONAL_100R.yaml`. Ledger:
`outputs/og_build_years/final_buildoff_A_build_years_trades.csv`. Every
number below was recomputed in this session directly from that ledger
(and cross-checked against `outputs/og_build_years/final_buildoff_be45.csv`,
row `candidate == "A"`) — none was copied from a prior doc without
recomputation.

## Ledger hash

```
sha256sum outputs/og_build_years/final_buildoff_A_build_years_trades.csv
3546c0768b57d99de92a76f24a84f1c492bb82e92a959ae04ef3ce51a508c168
```

This matches `expected_build_ledger.sha256` in
`configs/OG_OPERATIONAL_100R.yaml` exactly — **confirmed equal**.

## Build years used

2018 (full), 2020 (full), 2023 (full), 2026 (partial, through 2026-06-07).
407 total rows in the ledger.

## Per-year metrics

| year | n_trades | net_pts | PF_pts | PF_R | cap_norm_R_total | avg_R/trade | win_rate | avg_winner_pts | avg_loser_pts | payoff | max_dd_pts | max_dd_R | TP | SL | BE | cutoff | hold_mean_min | hold_median_min | prof_days | lose_days | BE_days | avg_daily_pnl | median_daily_pnl | longest_no-win_run |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2018 | 113 | 319.92 | 1.3565 | 1.4245 | 14.3037 | 0.1266 | 0.4248 | 25.359 | -26.392 | 0.961 | -177.38 | -5.6963 | 48 | 33 | 31 | 1 | 141.8 | 79.0 | 42 | 30 | 18 | 3.555 | 0.000 | 4 |
| 2020 | 137 | 1345.31 | 1.5744 | 1.0166 | 0.7581 | 0.0055 | 0.3431 | 78.452 | -48.790 | 1.608 | -721.54 | -8.0000 | 45 | 44 | 42 | 6 | 161.0 | 71.0 | 43 | 41 | 21 | 12.812 | 0.000 | 7 |
| 2023 | 100 | 494.53 | 1.2872 | 1.3316 | 9.7365 | 0.0974 | 0.4100 | 54.059 | -53.808 | 1.005 | -378.11 | -3.7536 | 39 | 28 | 27 | 6 | 126.7 | 61.5 | 38 | 27 | 21 | 5.750 | 0.000 | 7 |
| 2026 (partial) | 57 | 2533.00 | 3.2937 | 2.6596 | 19.6536 | 0.3448 | 0.5789 | 110.222 | -92.026 | 1.198 | -355.12 | -4.0000 | 31 | 11 | 12 | 3 | 163.0 | 61.0 | 31 | 9 | 7 | 53.894 | 84.375 | 3 |

## Completed years pooled (2018+2020+2023)

n=350, net_pts=2159.76, PF_pts=1.4353, PF_R=1.2282, cap_norm_R_total=24.7984,
avg_R/trade=0.0709, win_rate=0.3886, avg_winner=52.359, avg_loser=-43.519,
payoff=1.203, max_dd_pts=-721.54, max_dd_R=-8.0000, TP=132, SL=105, BE=100,
cutoff=13, hold_mean=145.0min, hold_median=71.5min, profitable_days=123,
losing_days=98, BE_days=60, avg_daily_pnl=7.686, median_daily_pnl=0.000,
longest_no-win_run=7.

## All build years pooled (+2026 partial) — explicit

n=407, net_pts=4692.76, PF_pts=1.7737, PF_R=1.3689, cap_norm_R_total=44.4520,
avg_R/trade=0.1092, win_rate=0.4152, avg_winner=63.658, avg_loser=-48.138,
payoff=1.322, max_dd_pts=-721.54, max_dd_R=-8.0000, TP=163, SL=116, BE=112,
cutoff=16, hold_mean=147.5min, hold_median=71.0min, profitable_days=154,
losing_days=107, BE_days=67, avg_daily_pnl=14.307, median_daily_pnl=0.000,
longest_no-win_run=7.

## Result excluding 2026

Identical to the "completed years pooled" row above: n=350,
avg_R/trade=0.0709, PF_R=1.2282, net_pts=2159.76.

## Result excluding the single best day (completed years only)

Best single day (completed years): 2020-03-20, +200.00 pts. Excluding it:
n=349, avg_R/trade=0.0682 (down from 0.0709).

## Result excluding the single best year (completed years only)

Best completed year: 2020, net_pts=1345.31. Excluding it (pooling
2018+2023 only): n=213, avg_R/trade=0.1129 (up from 0.0709 — as with
`OG_PRIMARY_150R`, 2020 is this config's weakest year on a per-trade
basis).

## Day-level metrics

Reused from `outputs/og_build_years/final_buildoff_daily_metrics.csv`
(candidate == "A"). Completed years: 123 profitable / 98 losing / 60
breakeven days (55.7% of non-BE days profitable). All build years incl.
2026: 154 profitable / 107 losing / 67 breakeven. Median daily P&L is 0.0
pts for completed years; 84.375 for all-build-years (the strong partial
2026 year pulls the pooled median off zero — the 2026-concentration
caveat already flagged in `docs/OG_PHASE1_FINAL_REPORT.md`).

## Exit-reason mix

Completed years: TP 132 / SL 105 / BE 100 / cutoff 13 (out of 350). All
build years: TP 163 / SL 116 / BE 112 / cutoff 16 (out of 407). TP is the
largest exit category in both scopes (unlike `OG_PRIMARY_150R`, where BE
is largest) — the easier-to-reach 1.00R target converts more trades to
outright TP before BE45 or the 15:00 cutoff intervene.

## Holding time

Completed years: mean 145.0 min, median 71.5 min. All build years: mean
147.5 min, median 71.0 min.
